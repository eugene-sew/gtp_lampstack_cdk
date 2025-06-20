#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status.
set -x  # Print commands and their arguments as they are executed.
exec > /var/log/user-data.log 2>&1
echo "Starting user data script execution"
yum update -y
yum install -y jq git unzip httpd mariadb

# Install AWS CLI v2
echo "Installing AWS CLI v2"
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip -q awscliv2.zip
./aws/install

# Install PHP 8.0
echo "Installing PHP 8.0"
amazon-linux-extras | grep php
yum remove -y php* || true
yum clean all
amazon-linux-extras enable php8.0
yum clean metadata
yum install -y php-cli php-fpm php-opcache php-common php-mysqlnd php-json

# Install CloudWatch Agent
echo "Installing CloudWatch Agent"
yum install -y amazon-cloudwatch-agent

# Start services
systemctl start httpd
systemctl enable httpd

# Clean web root and clone repository directly
echo "Cleaning /var/www/html/ directory..."
rm -rf /var/www/html/* /var/www/html/.* || true # Remove all files and hidden files, ignore errors if dir is empty
echo "Cloning repository directly into /var/www/html/..."
if git clone {{GITHUB_REPO_URL}} /var/www/html/; then
  echo "Repository cloned successfully into /var/www/html/."
else
  GIT_CLONE_EXIT_CODE=$?
  echo "Failed to clone repository directly into /var/www/html/ (Exit Code: $GIT_CLONE_EXIT_CODE). Creating fallback page."
  # Attempt to clean up again in case of partial clone before writing fallback
  rm -rf /var/www/html/* /var/www/html/.* || true
  echo "<html><body><h1>LAMP Stack is running!</h1><p>Failed to clone repository. Git Exit Code: $GIT_CLONE_EXIT_CODE</p></body></html>" > /var/www/html/index.html
fi

# Get region from instance metadata
echo "Getting instance region and secret name."
AWS_REGION=$(curl -s http://169.254.169.254/latest/meta-data/placement/region)
SECRET_NAME="{{DB_SECRET_NAME}}"
echo "Region: $AWS_REGION, Secret Name: $SECRET_NAME"

# Retrieve DB credentials from Secrets Manager with retry logic
MAX_RETRIES=5
for ((i=1; i<=MAX_RETRIES; i++)); do
  echo "Attempt $i of $MAX_RETRIES to get secret."
  SECRET=$(aws secretsmanager get-secret-value --secret-id $SECRET_NAME --region $AWS_REGION --query SecretString --output text 2>/dev/null)
  if [ $? -eq 0 ] && [ ! -z "$SECRET" ]; then
    echo "Secret successfully retrieved."
    break
  else
    echo "Failed to retrieve secret, retrying in 10 seconds..."
    sleep 10
  fi
done

# Clone GitHub repository
echo "Cloning repository: {{GITHUB_REPO_URL}}" > /var/www/html/git-clone.log
rm -rf /tmp/lamp-source # Clean up temp dir before use
mkdir -p /tmp/lamp-source
git clone {{GITHUB_REPO_URL}} /tmp/lamp-source
if [ $? -eq 0 ]; then
  echo "Repository cloned successfully to /tmp/lamp-source" >> /var/www/html/git-clone.log
  echo "Cleaning /var/www/html before copying new files..."
  rm -rf /var/www/html/*
  rm -rf /var/www/html/.* || true # Remove hidden files, ignore error if none except . and .. exist
  echo "Copying repository files to /var/www/html..."
  cp -r /tmp/lamp-source/* /var/www/html/ 2>/dev/null || true
  cp -r /tmp/lamp-source/.* /var/www/html/ 2>/dev/null || true
  rm -rf /tmp/lamp-source # Clean up temp dir after use
else
  echo "Failed to clone repository" >> /var/www/html/git-clone.log
  echo "<html><body><h1>LAMP Stack is running!</h1><p>Failed to clone repository</p></body></html>" > /var/www/html/index.html
fi

# Create .env file
LAMP_APP_SUBDIR="/var/www/html/lamp" # For application structure like config files
ENV_FILE_PATH="/var/www/html/.env"   # .env file in the web root
echo "Ensuring application subdirectory $LAMP_APP_SUBDIR exists (e.g., for lamp/config/db_config.php)."
mkdir -p $LAMP_APP_SUBDIR

echo "Attempting to create .env file at $ENV_FILE_PATH"
echo "Value of SECRET variable before parsing: [$SECRET]"

if [ ! -z "$SECRET" ]; then
  echo "SECRET variable is not empty. Parsing and writing to .env file."
  DB_HOST_VAL=$(echo "$SECRET" | jq -r ".host")
  DB_USER_VAL=$(echo "$SECRET" | jq -r ".username")
  DB_PASS_VAL=$(echo "$SECRET" | jq -r ".password")
  echo "Parsed DB_HOST: [$DB_HOST_VAL]"

  if [ -z "$DB_HOST_VAL" ] || [ "$DB_HOST_VAL" == "null" ]; then echo "Warning: DB_HOST_VAL is empty or null after jq."; fi

  echo "DB_HOST=$DB_HOST_VAL" > $ENV_FILE_PATH
  echo "DB_USER=$DB_USER_VAL" >> $ENV_FILE_PATH
  echo "DB_PASS=$DB_PASS_VAL" >> $ENV_FILE_PATH
else
  echo "SECRET variable IS EMPTY or retrieval failed. Using fallback database values for .env file."
  echo "DB_HOST={{DB_INSTANCE_ENDPOINT_ADDRESS}}" > $ENV_FILE_PATH
  echo "DB_USER=admin" >> $ENV_FILE_PATH
  echo "DB_PASS=password" >> $ENV_FILE_PATH
fi
echo "DB_NAME=lampapp" >> $ENV_FILE_PATH

echo "Checking .env file content after creation:"
cat $ENV_FILE_PATH || echo "Failed to cat $ENV_FILE_PATH or file is empty."
echo "Finished .env file creation attempt."

# Create a test PHP file
echo "Creating db-test.php..."
cat > /var/www/html/db-test.php << 'EOF'
<?php
require_once "/var/www/html/lamp/config/db_config.php";

echo "<h1>LAMP Stack Environment Test</h1>";
echo "<h2>PHP Version: " . phpversion() . "</h2>";

echo "<h2>Database Configuration:</h2>";
echo "<p>Host: " . DB_HOST . "</p>";
echo "<p>User: " . DB_USER . "</p>";
echo "<p>Database: " . DB_NAME . "</p>";

try {
    $conn = getDbConnection();
    echo "<h2 style='color:green'>Database Connection Successful!</h2>";
} catch (Exception $e) {
    echo "<h2 style='color:red'>Database Connection Failed!</h2>";
    echo "<p>Error: " . $e->getMessage() . "</p>";
}
EOF

# Set final permissions
echo "Setting final ownership and permissions..."
chown -R apache:apache /var/www/html
find /var/www/html -type d -exec chmod 755 {} \; # General directory permissions
find /var/www/html -type f -exec chmod 644 {} \; # General file permissions
if [ -f "$ENV_FILE_PATH" ]; then
  chmod 640 $ENV_FILE_PATH
  echo "Permissions specifically set for $ENV_FILE_PATH to 640."
else
  echo "Warning: $ENV_FILE_PATH not found for final chmod 640."
fi
# Configure CloudWatch Agent
echo "Configuring CloudWatch Agent"
cat > /opt/aws/amazon-cloudwatch-agent/bin/config.json << 'EOF_CW_AGENT'
{
  "agent": {
    "run_as_user": "root"
  },
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/httpd/access_log",
            "log_group_name": "LAMPSTACK-LOGGROUP",
            "log_stream_name": "{instance_id}",
            "timestamp_format": "%d/%b/%Y:%H:%M:%S %z"
          },
          {
            "file_path": "/var/log/httpd/error_log",
            "log_group_name": "LAMPSTACK-LOGGROUP",
            "log_stream_name": "{instance_id}"
          },
          {
            "file_path": "/var/log/messages",
            "log_group_name": "LAMPSTACK-LOGGROUP",
            "log_stream_name": "{instance_id}"
          },
          {
            "file_path": "/var/log/user-data.log",
            "log_group_name": "LAMPSTACK-LOGGROUP",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  }
}
EOF_CW_AGENT

# Start CloudWatch Agent
echo "Starting CloudWatch Agent"
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -c file:/opt/aws/amazon-cloudwatch-agent/bin/config.json -s
systemctl enable amazon-cloudwatch-agent
systemctl start amazon-cloudwatch-agent

echo "User data script finished."
