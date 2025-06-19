from aws_cdk import (
    Duration,
    Stack,
    aws_ec2 as ec2,
    aws_rds as rds,
    aws_elasticloadbalancingv2 as elbv2,
    aws_autoscaling as autoscaling,
    aws_iam as iam,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cloudwatch_actions,
    aws_sns as sns,
    aws_secretsmanager as secretsmanager,
    CfnOutput,
    RemovalPolicy,
    Tags,
)
from constructs import Construct

class LampStackArchitectureStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, github_repo_url: str = "https://github.com/eugene-sew/gtp_lampstack_lab_app.git", **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Tagging
        self.github_repo_url = github_repo_url
        
        # Add common tags to the stack
        Tags.of(self).add('Project', 'LAMP_LAB')
        Tags.of(self).add('Environment', 'Development')
        
        # Create VPC with public and private subnets across 2 AZs
        self.vpc = ec2.Vpc(
            self, "LampVPC",
            max_azs=2,
            ip_addresses=ec2.IpAddresses.cidr("10.0.0.0/16"),
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24
                )
            ],
            nat_gateways=2
        )
        
        # Add tags to VPC
        Tags.of(self.vpc).add('Project', 'LAMP_LAB')
        Tags.of(self.vpc).add('Environment', 'Development')
        
        # Security Groups
        # Load Balancer Security Group
        lb_security_group = ec2.SecurityGroup(
            self, "LAMP_LAB_LoadBalancerSG",
            vpc=self.vpc,
            description="Security group for the load balancer",
            allow_all_outbound=True
        )
        
        # Add tags to load balancer security group
        Tags.of(lb_security_group).add('Project', 'LAMP_LAB')
        Tags.of(lb_security_group).add('Environment', 'Development')
        lb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(80),
            "Allow HTTP traffic from the internet"
        )
        lb_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(443),
            "Allow HTTPS traffic from the internet"
        )
        
        # Web Server Security Group
        web_security_group = ec2.SecurityGroup(
            self, "LAMP_LAB_WebServerSG",
            vpc=self.vpc,
            description="Security group for the web servers",
            allow_all_outbound=True
        )
        
        # Add tags to web server security group
        Tags.of(web_security_group).add('Project', 'LAMP_LAB')
        Tags.of(web_security_group).add('Environment', 'Development')
        web_security_group.add_ingress_rule(
            lb_security_group,
            ec2.Port.tcp(80),
            "Allow HTTP traffic from the load balancer"
        )
        web_security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(),
            ec2.Port.tcp(22),
            "Allow SSH from anywhere"
        )
        
        # Database Security Group
        db_security_group = ec2.SecurityGroup(
            self, "LAMP_LAB_DatabaseSG",
            vpc=self.vpc,
            description="Security group for the database",
            allow_all_outbound=False
        )
        
        # Add tags to database security group
        Tags.of(db_security_group).add('Project', 'LAMP_LAB')
        Tags.of(db_security_group).add('Environment', 'Development')
        db_security_group.add_ingress_rule(
            web_security_group,
            ec2.Port.tcp(3306),
            "Allow MySQL traffic from the web servers"
        )
        
        # Create RDS MySQL Instance with credentials in Secrets Manager
        database = rds.DatabaseInstance(
            self, "LAMP_LAB_Database",
            engine=rds.DatabaseInstanceEngine.mysql(
                version=rds.MysqlEngineVersion.VER_8_0
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3,
                ec2.InstanceSize.SMALL
            ),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[db_security_group],
            multi_az=True,  # High availability
            allocated_storage=20,
            storage_type=rds.StorageType.GP2,
            database_name="lampapp",
            credentials=rds.Credentials.from_generated_secret("admin"),
            backup_retention=Duration.days(7),
            deletion_protection=False,
            removal_policy=RemovalPolicy.SNAPSHOT
        )
        
        # Get the auto-generated secret with database credentials
        db_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "DBSecret",
            secret_name=database.secret.secret_name
        )
        
        # Add tags to database
        Tags.of(database).add('Project', 'LAMP_LAB')
        Tags.of(database).add('Environment', 'Development')
        
        # Create Application Load Balancer
        alb = elbv2.ApplicationLoadBalancer(
            self, "LAMP_LAB_LoadBalancer",
            vpc=self.vpc,
            internet_facing=True,
            security_group=lb_security_group,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            )
        )
        
        # Add tags to load balancer
        Tags.of(alb).add('Project', 'LAMP_LAB')
        Tags.of(alb).add('Environment', 'Development')
        
        # Add listener to the ALB
        listener = alb.add_listener(
            "HttpListener",
            port=80,
            open=True
        )
        
        # Create user data script
        user_data_script = '#!/bin/bash\nset -e  # Exit immediately if a command exits with a non-zero status.\nset -x  # Print commands and their arguments as they are executed.\n'
        user_data_script += 'exec > /var/log/user-data.log 2>&1\n'
        user_data_script += 'echo "Starting user data script execution"\n'
        user_data_script += 'yum update -y\n'
        user_data_script += 'yum install -y jq git unzip httpd mariadb\n'
        
        # Install AWS CLI v2
        user_data_script += 'echo "Installing AWS CLI v2"\n'
        user_data_script += 'curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"\n'
        user_data_script += 'unzip -q awscliv2.zip\n'
        user_data_script += './aws/install\n'
        
        # Install PHP 8.0
        user_data_script += 'echo "Installing PHP 8.0"\n'
        user_data_script += 'amazon-linux-extras | grep php\n'
        user_data_script += 'yum remove -y php* || true\n'
        user_data_script += 'yum clean all\n'
        user_data_script += 'amazon-linux-extras enable php8.0\n'
        user_data_script += 'yum clean metadata\n'
        user_data_script += 'yum install -y php-cli php-fpm php-opcache php-common php-mysqlnd php-json\n'
        
        # Start services
        user_data_script += 'systemctl start httpd\n'
        user_data_script += 'systemctl enable httpd\n'
        
        # Clean web root and clone repository directly
        user_data_script += 'echo "Cleaning /var/www/html/ directory..."\n'
        user_data_script += 'rm -rf /var/www/html/* /var/www/html/.* || true # Remove all files and hidden files, ignore errors if dir is empty\n'
        user_data_script += 'echo "Cloning repository directly into /var/www/html/..."\n'
        user_data_script += f'if git clone {self.github_repo_url} /var/www/html/; then\n'
        user_data_script += '  echo "Repository cloned successfully into /var/www/html/."\n'
        user_data_script += 'else\n'
        user_data_script += '  GIT_CLONE_EXIT_CODE=$?\n'
        user_data_script += '  echo "Failed to clone repository directly into /var/www/html/ (Exit Code: $GIT_CLONE_EXIT_CODE). Creating fallback page."\n'
        user_data_script += '  # Attempt to clean up again in case of partial clone before writing fallback\n'
        user_data_script += '  rm -rf /var/www/html/* /var/www/html/.* || true\n'
        user_data_script += '  echo "<html><body><h1>LAMP Stack is running!</h1><p>Failed to clone repository. Git Exit Code: $GIT_CLONE_EXIT_CODE</p></body></html>" > /var/www/html/index.html\n'
        user_data_script += 'fi\n'
        
        # Get region from instance metadata
        user_data_script += 'echo "Getting instance region and secret name."\n'
        user_data_script += 'AWS_REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)\n'
        user_data_script += f'SECRET_NAME="{database.secret.secret_name}"\n'
        user_data_script += 'echo "Region: $AWS_REGION, Secret Name: $SECRET_NAME"\n'
        
        # Retrieve DB credentials from Secrets Manager with retry logic
        user_data_script += 'MAX_RETRIES=5\n'
        user_data_script += 'for ((i=1; i<=MAX_RETRIES; i++)); do\n'
        user_data_script += '  echo "Attempt $i of $MAX_RETRIES to get secret."\n'
        user_data_script += '  SECRET=$(aws secretsmanager get-secret-value --secret-id $SECRET_NAME --region $AWS_REGION --query SecretString --output text 2>/dev/null)\n'
        user_data_script += '  if [ $? -eq 0 ] && [ ! -z "$SECRET" ]; then\n'
        user_data_script += '    echo "Secret successfully retrieved."\n'
        user_data_script += '    break\n'
        user_data_script += '  else\n'
        user_data_script += '    echo "Failed to retrieve secret, retrying in 10 seconds..."\n'
        user_data_script += '    sleep 10\n'
        user_data_script += '  fi\n'
        user_data_script += 'done\n'
        
        # Clone GitHub repository
        user_data_script += f'echo "Cloning repository: {self.github_repo_url}" > /var/www/html/git-clone.log\n'
        user_data_script += 'rm -rf /tmp/lamp-source # Clean up temp dir before use\n'
        user_data_script += 'mkdir -p /tmp/lamp-source\n'
        user_data_script += f'git clone {self.github_repo_url} /tmp/lamp-source\n'
        user_data_script += 'if [ $? -eq 0 ]; then\n'
        user_data_script += '  echo "Repository cloned successfully to /tmp/lamp-source" >> /var/www/html/git-clone.log\n'
        user_data_script += '  echo "Cleaning /var/www/html before copying new files..."\n'
        user_data_script += '  rm -rf /var/www/html/*\n'
        user_data_script += '  rm -rf /var/www/html/.* || true # Remove hidden files, ignore error if none except . and .. exist\n'
        user_data_script += '  echo "Copying repository files to /var/www/html..."\n'
        user_data_script += '  cp -r /tmp/lamp-source/* /var/www/html/ 2>/dev/null || true\n'
        user_data_script += '  cp -r /tmp/lamp-source/.* /var/www/html/ 2>/dev/null || true\n'
        user_data_script += '  rm -rf /tmp/lamp-source # Clean up temp dir after use\n'
        user_data_script += 'else\n'
        user_data_script += '  echo "Failed to clone repository" >> /var/www/html/git-clone.log\n'
        user_data_script += '  echo "<html><body><h1>LAMP Stack is running!</h1><p>Failed to clone repository</p></body></html>" > /var/www/html/index.html\n'
        user_data_script += 'fi\n'

        # Create .env file
        user_data_script += 'LAMP_APP_SUBDIR="/var/www/html/lamp" # For application structure like config files\n'
        user_data_script += 'ENV_FILE_PATH="/var/www/html/.env"   # .env file in the web root\n'
        user_data_script += 'echo "Ensuring application subdirectory $LAMP_APP_SUBDIR exists (e.g., for lamp/config/db_config.php)."\n'
        user_data_script += 'mkdir -p $LAMP_APP_SUBDIR\n'

        user_data_script += 'echo "Attempting to create .env file at $ENV_FILE_PATH"\n'
        user_data_script += 'echo "Value of SECRET variable before parsing: [$SECRET]"\n'

        user_data_script += 'if [ ! -z "$SECRET" ]; then\n'
        user_data_script += '  echo "SECRET variable is not empty. Parsing and writing to .env file."\n'
        user_data_script += '  DB_HOST_VAL=$(echo "$SECRET" | jq -r ".host")\n'
        user_data_script += '  DB_USER_VAL=$(echo "$SECRET" | jq -r ".username")\n'
        user_data_script += '  DB_PASS_VAL=$(echo "$SECRET" | jq -r ".password")\n'
        user_data_script += '  echo "Parsed DB_HOST: [$DB_HOST_VAL]"\n'

        user_data_script += '  if [ -z "$DB_HOST_VAL" ] || [ "$DB_HOST_VAL" == "null" ]; then echo "Warning: DB_HOST_VAL is empty or null after jq."; fi\n'

        user_data_script += '  echo "DB_HOST=$DB_HOST_VAL" > $ENV_FILE_PATH\n'
        user_data_script += '  echo "DB_USER=$DB_USER_VAL" >> $ENV_FILE_PATH\n'
        user_data_script += '  echo "DB_PASS=$DB_PASS_VAL" >> $ENV_FILE_PATH\n'
        user_data_script += 'else\n'
        user_data_script += '  echo "SECRET variable IS EMPTY or retrieval failed. Using fallback database values for .env file."\n'
        user_data_script += f'  echo "DB_HOST={database.db_instance_endpoint_address}" > $ENV_FILE_PATH\n'
        user_data_script += '  echo "DB_USER=admin" >> $ENV_FILE_PATH\n'
        user_data_script += '  echo "DB_PASS=password" >> $ENV_FILE_PATH\n'
        user_data_script += 'fi\n'
        user_data_script += 'echo "DB_NAME=lampapp" >> $ENV_FILE_PATH\n'

        user_data_script += 'echo "Checking .env file content after creation:"\n'
        user_data_script += 'cat $ENV_FILE_PATH || echo "Failed to cat $ENV_FILE_PATH or file is empty."\n'
        user_data_script += 'echo "Finished .env file creation attempt."\n'

        # Create a test PHP file
        user_data_script += 'echo "Creating db-test.php..."\n'
        user_data_script += 'cat > /var/www/html/db-test.php << \'EOF\'\n'
        user_data_script += '<?php\n'
        user_data_script += 'require_once "/var/www/html/lamp/config/db_config.php";\n\n'
        user_data_script += 'echo "<h1>LAMP Stack Environment Test</h1>";\n'
        user_data_script += 'echo "<h2>PHP Version: " . phpversion() . "</h2>";\n\n'
        user_data_script += 'echo "<h2>Database Configuration:</h2>";\n'
        user_data_script += 'echo "<p>Host: " . DB_HOST . "</p>";\n'
        user_data_script += 'echo "<p>User: " . DB_USER . "</p>";\n'
        user_data_script += 'echo "<p>Database: " . DB_NAME . "</p>";\n\n'
        user_data_script += 'try {\n'
        user_data_script += '    $conn = getDbConnection();\n'
        user_data_script += '    echo "<h2 style=\'color:green\'>Database Connection Successful!</h2>";\n'
        user_data_script += '} catch (Exception $e) {\n'
        user_data_script += '    echo "<h2 style=\'color:red\'>Database Connection Failed!</h2>";\n'
        user_data_script += '    echo "<p>Error: " . $e->getMessage() . "</p>";\n'
        user_data_script += '}\n'
        user_data_script += 'EOF\n'

        # Set final permissions
        user_data_script += 'echo "Setting final ownership and permissions..."\n'
        user_data_script += 'chown -R apache:apache /var/www/html\n'
        user_data_script += 'find /var/www/html -type d -exec chmod 755 {} \\; # General directory permissions\n'
        user_data_script += 'find /var/www/html -type f -exec chmod 644 {} \\; # General file permissions\n'
        user_data_script += 'if [ -f "$ENV_FILE_PATH" ]; then\n'
        user_data_script += '  chmod 640 $ENV_FILE_PATH\n'
        user_data_script += '  echo "Permissions specifically set for $ENV_FILE_PATH to 640."\n'
        user_data_script += 'else\n'
        user_data_script += '  echo "Warning: $ENV_FILE_PATH not found for final chmod 640."\n'
        user_data_script += 'fi\n'
        user_data_script += 'echo "User data script finished."\n'
        
        # Create user data from script
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(user_data_script)
        
        # Create IAM role for EC2 instances with necessary permissions
        web_server_role = iam.Role(
            self, "WebServerRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com")
        )
        
        # Grant the web server role permissions to read the database secret
        database.secret.grant_read(web_server_role)
        
        # Add policy to allow EC2 instances to describe themselves (for instance metadata)
        web_server_role.add_to_policy(iam.PolicyStatement(
            actions=["ec2:DescribeInstances", "ec2:DescribeTags", "ec2:CreateTags"],
            resources=["*"]
        ))
        
        # Create Auto Scaling Group with EC2 instances
        self.asg = autoscaling.AutoScalingGroup(
            self, "LAMP_LAB_AutoScalingGroup",
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PUBLIC
            ),
            instance_type=ec2.InstanceType.of(
                ec2.InstanceClass.BURSTABLE3,
                ec2.InstanceSize.SMALL
            ),
            machine_image=ec2.AmazonLinuxImage(
                generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2
            ),
            security_group=web_security_group,
            user_data=user_data,
            desired_capacity=2,
            min_capacity=2,
            max_capacity=4,
            key_name="LAMP_kp",
            role=web_server_role  # Assign IAM role to instances
        )
        self.asg.health_check_grace_period = Duration.minutes(5)
        
        # Add tags to Auto Scaling Group
        Tags.of(self.asg).add('Project', 'LAMP_LAB')
        Tags.of(self.asg).add('Environment', 'Development')
            
        # Add specific tag for EC2 instances created by the ASG
        self.asg.add_user_data("aws ec2 create-tags --resources $(curl -s http://169.254.169.254/latest/meta-data/instance-id) --tags Key=Name,Value=LAMP_LAB_WebServer Key=Project,Value=LAMP_LAB Key=Environment,Value=Development --region $(curl -s http://169.254.169.254/latest/meta-data/placement/region)")

        
        # Add the ASG as a target to the ALB listener
        listener.add_targets(
            "WebServerTargets",
            port=80,
            targets=[self.asg],
            health_check={
                "path": "/",
                "interval": Duration.seconds(30),
                "timeout": Duration.seconds(5),
                "healthy_threshold_count": 2,
                "unhealthy_threshold_count": 5
            }
        )
        
        # Scale the ASG based on CPU utilization
        self.asg.scale_on_cpu_utilization(
            "CpuScaling",
            target_utilization_percent=70,
            cooldown=Duration.minutes(5)
        )
        
        # Output the load balancer DNS name
        CfnOutput(
            self, "LoadBalancerDNS",
            value=alb.load_balancer_dns_name,
            description="The DNS name of the load balancer"
        )
        
        # Output the database endpoint
        CfnOutput(
            self, "DatabaseEndpoint",
            value=database.db_instance_endpoint_address,
            description="The endpoint of the database"
        )
        
        # Output the Secrets Manager secret name
        CfnOutput(
            self, "DatabaseSecretName",
            value=database.secret.secret_name,
            description="The name of the secret containing database credentials"
        )
        
        # Create an SNS topic for CloudWatch alarms
        alarm_topic = sns.Topic(
            self, "LAMP_LAB_AlarmTopic",
            display_name="LAMP_LAB_Alarms",
            topic_name="LAMP_LAB_Alarms"
        )
        
        # Add tags to SNS topic
        Tags.of(alarm_topic).add('Project', 'LAMP_LAB')
        Tags.of(alarm_topic).add('Environment', 'Development')
        
        # Output the SNS topic ARN
        CfnOutput(
            self, "AlarmTopicArn",
            value=alarm_topic.topic_arn,
            description="The ARN of the SNS topic for alarms"
        )
        
        # CloudWatch alarms for key metrics
        
        # 1. High CPU Utilization Alarm for Auto Scaling Group
        high_cpu_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_HighCPUAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/AutoScaling",
                metric_name="CPUUtilization",
                dimensions_map={
                    "AutoScalingGroupName": self.asg.auto_scaling_group_name
                },
                statistic="Average",
                period=Duration.minutes(5)
            ),
            evaluation_periods=2,
            threshold=90,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="Alarm if CPU utilization is greater than 90% for 2 consecutive periods",
            alarm_name="LAMP_LAB_HighCPUUtilization"
        )
        high_cpu_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        
        # 2. Low CPU Credits Alarm for EC2 instances (for burstable instances)
        low_cpu_credits_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_LowCPUCreditsAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/EC2",
                metric_name="CPUCreditBalance",
                dimensions_map={
                    "AutoScalingGroupName": self.asg.auto_scaling_group_name
                },
                statistic="Average"
            ),
            evaluation_periods=3,
            threshold=20,  # Low CPU credit balance
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            alarm_description="Alarm if CPU credit balance is less than 20 for 3 consecutive periods",
            alarm_name="LAMP_LAB_LowCPUCredits"
        )
        low_cpu_credits_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        
        # 3. High Database CPU Utilization Alarm
        db_high_cpu_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_DBHighCPUAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="CPUUtilization",
                dimensions_map={
                    "DBInstanceIdentifier": database.instance_identifier
                },
                statistic="Average"
            ),
            evaluation_periods=3,
            threshold=80,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="Alarm if database CPU utilization is greater than 80% for 3 consecutive periods",
            alarm_name="LAMP_LAB_DBHighCPUUtilization"
        )
        db_high_cpu_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        
        # 4. Low Database Free Storage Space Alarm
        db_low_storage_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_DBLowStorageAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="FreeStorageSpace",
                dimensions_map={
                    "DBInstanceIdentifier": database.instance_identifier
                },
                statistic="Average"
            ),
            evaluation_periods=3,
            threshold=2000000000,  # 2GB in bytes
            comparison_operator=cloudwatch.ComparisonOperator.LESS_THAN_THRESHOLD,
            alarm_description="Alarm if database free storage space is less than 2GB for 3 consecutive periods",
            alarm_name="LAMP_LAB_DBLowStorage"
        )
        db_low_storage_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        
        # 5. High Database Connections Alarm
        db_connections_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_DBConnectionsAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/RDS",
                metric_name="DatabaseConnections",
                dimensions_map={
                    "DBInstanceIdentifier": database.instance_identifier
                },
                statistic="Average"
            ),
            evaluation_periods=3,
            threshold=100,  # Adjust based on your database instance type
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="Alarm if database connections exceed 100 for 3 consecutive periods",
            alarm_name="LAMP_LAB_DBHighConnections"
        )
        db_connections_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        
        # 6. ALB High Latency Alarm
        alb_latency_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_ALBLatencyAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ApplicationELB",
                metric_name="TargetResponseTime",
                dimensions_map={
                    "LoadBalancer": alb.load_balancer_full_name
                },
                statistic="Average"
            ),
            evaluation_periods=3,
            threshold=2,  # 2 seconds
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="Alarm if ALB target response time is greater than 2 seconds for 3 consecutive periods",
            alarm_name="LAMP_LAB_ALBHighLatency"
        )
        alb_latency_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
        
        # 7. ALB 5XX Error Rate Alarm
        alb_5xx_alarm = cloudwatch.Alarm(
            self, "LAMP_LAB_ALB5XXAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/ApplicationELB",
                metric_name="HTTPCode_ELB_5XX_Count",
                dimensions_map={
                    "LoadBalancer": alb.load_balancer_full_name
                },
                statistic="Sum"
            ),
            evaluation_periods=3,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            alarm_description="Alarm if ALB returns more than 10 5XX errors for 3 consecutive periods",
            alarm_name="LAMP_LAB_ALB5XXErrors"
        )
        alb_5xx_alarm.add_alarm_action(cloudwatch_actions.SnsAction(alarm_topic))
