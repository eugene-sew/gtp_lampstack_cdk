# LAMP Stack CDK Implementation Guide: Full Application Deployment

## 0. Lab Project: PROXIES - FULL APPLICATION DEPLOYMENT

### 0.1. Project Overview & Objectives

**Goal:**
The primary goal of this project is to deploy a LAMP Stack application behind a reverse proxy or load balancer. A key requirement is the integration of monitoring, logging, and observability tools from the outset to ensure real-time insight into the application's performance and availability.

**Deliverables:**

1.  **Functional Load-Balancing/Reverse Proxy:** A fully operational load-balancing or reverse proxy setup. This implementation utilizes AWS-based services, specifically the Application Load Balancer (ALB).
2.  **Monitoring & Logging:**
    - Centralized or distributed logging (achieved via EC2 instance logs and potential for CloudWatch Logs integration).
    - Comprehensive monitoring and alerting capabilities (implemented using CloudWatch metrics and alarms).
3.  **Observability:**
    - Detailed documentation (this document) and demonstrations of the full setup.
    - Considerations for security and performance testing are embedded in the design.

This document details the AWS CDK stack (`lamp_stack_architecture_stack.py`) created to meet these objectives.

## 1. Architectural Overview

The AWS CDK stack provisions a highly available, secure, and scalable infrastructure for a LAMP (Linux, Apache, MySQL, PHP) application. It leverages various AWS services to achieve robust load balancing, fault tolerance, automated scaling, and comprehensive monitoring, directly addressing the lab's core requirements.

## 2. Core Infrastructure

### 2.1. Virtual Private Cloud (VPC)

- **`ec2.Vpc` (`LampVPC`)**: Provides an isolated network environment.
  - **High Availability**: Spans two Availability Zones (AZs) (`max_azs=2`).
  - **Network Segmentation**:
    - **Public Subnets**: Host the Application Load Balancer and NAT Gateways.
    - **Private Subnets (`PRIVATE_WITH_EGRESS`)**: Securely host web servers (EC2 instances) and the RDS database instance, allowing outbound internet access via NAT Gateways.
  - **NAT Gateways**: Two NAT Gateways ensure high availability for outbound internet connectivity from private subnets.

### 2.2. Security Groups

Virtual firewalls enforce traffic rules:

- **Load Balancer Security Group (`LAMP_LAB_LoadBalancerSG`)**:

  - Allows inbound HTTP (port 80) and HTTPS (port 443) from the internet.
  - Allows all outbound traffic (to web servers).

- **Web Server Security Group (`LAMP_LAB_WebServerSG`)**:

  - Allows inbound HTTP (port 80) _only_ from the Load Balancer Security Group.
  - Allows inbound SSH (port 22) from anywhere (for development).
  - Allows all outbound traffic (for updates, code cloning, AWS service access).

- **Database Security Group (`LAMP_LAB_DatabaseSG`)**:
  - Allows inbound MySQL (port 3306) _only_ from the Web Server Security Group.
  - Restricts all outbound traffic from the database.

## 3. Application Components & Load Balancing

### 3.1. RDS MySQL Database Instance (`LAMP_LAB_Database`)

- **Managed Service**: MySQL 8.0, `t3.small` instance.
- **High Availability**: `multi_az=True` for automatic failover.
- **Security**: Resides in private subnets, access controlled by `db_security_group`.
- **Credentials Management**: `rds.Credentials.from_generated_secret("admin")` securely stores credentials in AWS Secrets Manager.
- **Backup & Recovery**: Automated backups (7-day retention) and `RemovalPolicy.SNAPSHOT`.

### 3.2. Application Load Balancer (ALB) (`LAMP_LAB_LoadBalancer`)

This is the core component addressing the "reverse proxy/load balancer" requirement.

- **Function**: Distributes incoming HTTP traffic across EC2 web servers in multiple AZs.
- **Accessibility**: `internet_facing=True`, placed in public subnets.
- **Listener (`HttpListener`)**: Listens on port 80 (HTTP) and forwards traffic to the Auto Scaling Group.
  - _For HTTPS, an SSL/TLS certificate and an HTTPS listener would be added._

### 3.3. EC2 Instance User Data Script (Web Server Configuration)

Executed on instance launch to set up Apache, PHP, and deploy the application.

- **Robust Scripting**: `set -e` (exit on error), `set -x` (trace execution).
- **Logging (Instance Level)**: All script output redirected to `/var/log/user-data.log` for **observability** into the setup process.
- **Software Stack**:
  - `yum update`, Apache (`httpd`), `jq`, `git`, AWS CLI v2.
  - PHP 8.0 with necessary extensions (`php-mysqlnd`, `php-json`, etc.).
- **Application Deployment**:
  - Clones the application from `self.github_repo_url` into `/var/www/html/`.
  - Includes error handling for clone failures.
- **Database Integration**:
  - Securely retrieves DB credentials from Secrets Manager using the instance's IAM role.
  - Implements retry logic for secret retrieval.
  - Creates an `.env` file in `/var/www/html/.env` with DB connection details.
- **Diagnostic Tool (`db-test.php`)**: A test PHP page is created at `/var/www/html/db-test.php`. This page:
  - Displays PHP version and DB configuration.
  - Tests database connectivity.
  - Serves as a crucial **observability** tool for quick instance health checks.
- **Permissions**: Sets appropriate ownership (`apache:apache`) and file/directory permissions for `/var/www/html/`, including restricted permissions for `.env`.

### 3.4. Auto Scaling Group (ASG) (`LAMP_LAB_AutoScalingGroup`)

Manages the fleet of EC2 web servers.

- **Scalability & Resilience**:
  - Launches `t3.small` instances with Amazon Linux 2.
  - `desired_capacity=2`, `min_capacity=2`, `max_capacity=4`.
  - Instances are launched across AZs, using the `web_security_group` and `user_data` script.
- **IAM Role (`WebServerRole`)**:
  - Grants instances permission to read the database secret from Secrets Manager.
  - Allows instances to describe themselves and manage their tags.
- **Health Checks**:
  - `health_check_grace_period = Duration.minutes(5)` allows time for user data script completion.
  - ALB performs health checks on `/` path of instances. Unhealthy instances are replaced by the ASG.
- **Automated Scaling**:
  - `asg.scale_on_cpu_utilization("CpuScaling", target_utilization_percent=70)`: Scales out/in based on average CPU load, maintaining performance and optimizing costs.
  - `cooldown=Duration.minutes(5)` prevents rapid scaling fluctuations.

## 4. Monitoring, Logging, and Observability (Lab Deliverables)

This section directly addresses the lab's requirements for monitoring, logging, and observability, primarily using AWS CloudWatch.

### 4.1. Centralized Notifications: SNS Topic (`LAMP_LAB_AlarmTopic`)

- An SNS topic is created to consolidate all alarm notifications.
- Subscribers (e.g., email, SMS, Lambda) can be added to this topic to receive real-time alerts.

### 4.2. Comprehensive Monitoring & Alerting: CloudWatch Alarms

A suite of CloudWatch alarms provides real-time insight into system health and performance, triggering notifications via the SNS topic.

- **EC2 / Auto Scaling Group Alarms**:
  1.  **`LAMP_LAB_HighCPUAlarm`**: ASG CPU Utilization > 90%.
  2.  **`LAMP_LAB_LowCPUCreditsAlarm`**: EC2 CPU Credit Balance < 20 (for T3 instances).
- **RDS Database Alarms**: 3. **`LAMP_LAB_DBHighCPUAlarm`**: Database CPU Utilization > 80%. 4. **`LAMP_LAB_DBLowStorageAlarm`**: Database Free Storage < 2GB. 5. **`LAMP_LAB_DBConnectionsAlarm`**: Database Connections > 100 (threshold adjustable).
- **Application Load Balancer Alarms**: 6. **`LAMP_LAB_ALBLatencyAlarm`**: ALB Target Response Time > 2 seconds. 7. **`LAMP_LAB_ALB5XXAlarm`**: ALB-generated 5XX errors > 10.

These alarms ensure that deviations from normal operational parameters are quickly identified and communicated.

### 4.3. Logging Strategy

- **Instance-Level Logging**:
  - **User Data Script Log**: `/var/log/user-data.log` on each EC2 instance captures the entire bootstrap process, crucial for diagnosing launch issues.
  - **Apache Logs**: Standard Apache access (`/var/log/httpd/access_log`) and error (`/var/log/httpd/error_log`) logs are available on each web server. These provide detailed insights into web requests and application-level errors.
- **Potential for Centralized Logging (CloudWatch Logs)**:
  - While not explicitly configured to stream to CloudWatch Logs in this version of the script, the AWS CloudWatch Agent can be installed on EC2 instances to forward Apache logs, application logs, and system logs to CloudWatch Logs. This would provide a centralized logging solution, fulfilling a key lab deliverable.
- **RDS Logs**: RDS can be configured to publish its logs (error, slow query, general) to CloudWatch Logs for analysis.

### 4.4. Observability Tools & Practices

Observability is achieved through a combination of metrics, logs, traces (implicitly via logs), and purpose-built tools:

- **`db-test.php` Page**: A simple but effective tool on each web server to quickly verify PHP environment and database connectivity. This is a direct method for observing the health of individual application nodes.
- **CloudWatch Metrics & Dashboards**: The numerous metrics collected by CloudWatch for EC2, RDS, ALB, and ASG provide deep insights. These can be visualized on CloudWatch Dashboards for a holistic view of the system's state.
- **ALB Access Logs (Recommended Enhancement)**: Configuring ALB access logs to be stored in S3 would provide detailed request tracing capabilities, invaluable for debugging and performance analysis.
- **User Data Script Tracing (`set -x`)**: The `set -x` option in the user data script provides a trace of commands executed during instance setup, logged to `/var/log/user-data.log`.
- **Tagging**: Consistent tagging (`Project: LAMP_LAB`, `Environment: Development`) across all resources aids in organizing, filtering, and understanding the components of the system, contributing to overall observability.

## 5. Security Considerations

- **Network Segmentation**: Use of public and private subnets.
- **Security Groups**: Principle of least privilege applied to firewall rules.
- **Secrets Management**: Database credentials managed by AWS Secrets Manager.
- **IAM Roles**: EC2 instances use IAM roles for AWS service access, avoiding static credentials on instances.
- **SSH Access**: While currently open from `0.0.0.0/0` for web servers, this should be restricted in production (e.g., to a bastion host or specific IPs).
- **HTTPS (Recommended Enhancement)**: The ALB listener is HTTP. For production, an HTTPS listener with an SSL/TLS certificate (e.g., from AWS Certificate Manager) is essential for encrypting data in transit.
- **Regular Patching**: The `yum update -y` in user data helps, but a consistent patching strategy is needed.

## 6. Performance Testing Considerations

- **Load Testing Tools**: Tools like Apache JMeter, k6, or Locust can be used to simulate traffic against the `LoadBalancerDNS` to understand how the system performs under various load conditions.
- **Monitoring During Tests**: Closely monitor CloudWatch metrics (CPU, memory, network, disk I/O for EC2 and RDS; latency, error rates for ALB; ASG scaling activities) during performance tests.
- **Bottleneck Identification**: Analyze metrics to identify bottlenecks (e.g., database, web server CPU, network).
- **Optimize Configuration**: Adjust instance types, ASG scaling policies, database parameters, and application code based on test results.
- **`db-test.php`**: Can be used for quick checks but is not a performance testing tool.

## 7. CloudFormation Outputs

Key identifiers for accessing and managing the deployed infrastructure:

- **`LoadBalancerDNS`**: URL to access the application.
- **`DatabaseEndpoint`**: RDS instance endpoint.
- **`DatabaseSecretName`**: Name of the secret in Secrets Manager.
- **`AlarmTopicArn`**: ARN of the SNS topic for alarm notifications.

## 8. Conclusion

This AWS CDK stack successfully deploys a LAMP application behind an Application Load Balancer, meeting the core requirements of the "PROXIES: FULL APPLICATION DEPLOYMENT" lab. It establishes a robust foundation with high availability, scalability, and a strong emphasis on monitoring, logging, and observability through integrated AWS services like CloudWatch, SNS, and Secrets Manager. Further enhancements, such as centralized CloudWatch Logs integration for application/web server logs and enabling HTTPS, would make it even more production-ready.
