# Cloudwatch Agent

## Description

Installs and configures the AWS [CloudWatch
Agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Install-CloudWatch-Agent.html)
on a host, in order to collect detailed metrics such as memory and disk usage.

Additionally, this role creates a systemd service (`cloudwatch_agent.service`) which starts the
agent automatically when the host is rebooted.

The host must be able to access the CloudWatch Logs API endpoint, via open outgoing port 443 access
to either the public Internet or a [VPC
endpoint](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/cloudwatch-logs-and-interface-VPC.html).
Additionally, the host must have an attached [IAM
role](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/create-iam-roles-for-cloudwatch-agent-commandline.html)
granting write permissions for CloudWatch Logs. The [EC2 metadata
service](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html) must be
reachable from the host.

The agent will automatically be upgraded to the latest available version whenever this role is run.

## Role Variables

| Name | Description | Default |
| --- | --- | --- |
| config_contents | Agent [configuration](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Agent-Configuration-File-Details.html) as a nested map of string to any type. | <pre lang="yaml">metrics:&#13;  metrics_collected:&#13;    mem:&#13;      measurement: ["used_percent"]&#13;    disk:&#13;      resources: ["/"]&#13;      measurement: ["used_percent"]</pre> |
