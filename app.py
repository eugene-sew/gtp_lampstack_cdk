#!/usr/bin/env python3
import os
import sys

import aws_cdk as cdk

from lamp_stack_architecture.lamp_stack_architecture_stack import LampStackArchitectureStack


app = cdk.App()


# Get GitHub repository URL from context or command line arguments
github_repo_url = app.node.try_get_context('github_repo_url')

# Create the LAMP stack
LampStackArchitectureStack(app, "LampStackArchitectureStack",
    github_repo_url=github_repo_url,
    # If you don't specify 'env', this stack will be environment-agnostic.
    # Account/Region-dependent features and context lookups will not work,
    # but a single synthesized template can be deployed anywhere.

    # Uncomment the next line to specialize this stack for the AWS Account
    # and Region that are implied by the current CLI configuration.
    
    env=cdk.Environment(account=os.getenv('CDK_DEFAULT_ACCOUNT'), region=os.getenv('CDK_DEFAULT_REGION')),

    # For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html
    )

app.synth()
