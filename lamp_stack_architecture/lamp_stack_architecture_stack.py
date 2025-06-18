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
    CfnOutput,
    RemovalPolicy,
    Tags,
)
from constructs import Construct

class LampStackArchitectureStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, github_repo_url: str = None, **kwargs) -> None:
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
        
        # Create RDS MySQL Instance
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
        
        # Create user data for EC2 instances
        user_data = ec2.UserData.for_linux()
        user_data.add_commands(
            "yum update -y",  # Amazon Linux 2
            # PHP 8.0 installation
            "amazon-linux-extras | grep php",  # Check available PHP versions
            "sudo yum remove php* -y",  # Remove existing PHP
            "sudo yum clean all",
            "sudo amazon-linux-extras enable php8.0",  # Enable PHP 8.0
            "sudo yum clean metadata",
            "sudo yum install -q -y php-cli php-fpm php-opcache php-common php-mysqlnd httpd mariadb-server git",
            # Start and enable services
            "systemctl start httpd",
            "systemctl enable httpd",
            "systemctl start mariadb",
            "systemctl enable mariadb",
            # Output PHP version for verification
            "echo 'PHP version installed:' > /var/www/html/php-version.txt",
            "php -v >> /var/www/html/php-version.txt",
            # Clone the GitHub repository if provided
            f"if [ ! -z '{self.github_repo_url}' ]; then",
            f"  git clone {self.github_repo_url} /var/www/html/",
            "else",
            "  echo '<html><body><h1>LAMP Stack is running!</h1></body></html>' > /var/www/html/index.html",
            "fi",
            # Create a PHP test file to verify database connection
            "echo '<?php" +
            "\n  $servername = \"" + database.db_instance_endpoint_address + "\";" +
            "\n  $username = \"admin\";" +
            "\n  $password = \"PLACEHOLDER_PASSWORD\";" +  # Will be replaced during deployment
            "\n  $dbname = \"lampapp\";" +
            "\n  // Create connection" +
            "\n  $conn = new mysqli($servername, $username, $password, $dbname);" +
            "\n  // Check connection" +
            "\n  if ($conn->connect_error) {" +
            "\n    die(\"Connection failed: \" . $conn->connect_error);" +
            "\n  }" +
            "\n  $conn->set_charset(\"utf8\");" +
            "\n  echo \"Connected successfully\";" +
            "\n?>' > /var/www/html/db-test.php",
        )
        
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
            key_name="LAMP_kp"
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
        
        # Create CloudWatch alarms for key metrics
        
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
