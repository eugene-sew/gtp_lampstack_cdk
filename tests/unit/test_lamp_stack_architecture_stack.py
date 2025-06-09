import aws_cdk as core
import aws_cdk.assertions as assertions

from lamp_stack_architecture.lamp_stack_architecture_stack import LampStackArchitectureStack

# example tests. To run these tests, uncomment this file along with the example
# resource in lamp_stack_architecture/lamp_stack_architecture_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = LampStackArchitectureStack(app, "lamp-stack-architecture")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
