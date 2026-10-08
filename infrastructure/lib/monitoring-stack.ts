import * as cdk from 'aws-cdk-lib';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import * as kinesis from 'aws-cdk-lib/aws-kinesis';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import { Construct } from 'constructs';

export interface MonitoringStackProps extends cdk.StackProps {
  environment: string;
  kinesisStream: kinesis.Stream;
  bronzeLambda: lambda.Function;
  ecsService: ecs.FargateService;
}

export class MonitoringStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: MonitoringStackProps) {
    super(scope, id, props);

    // Dashboard
    const dashboard = new cloudwatch.Dashboard(this, 'FraudDashboard', {
      dashboardName: `fraud-detection-${props.environment}`,
    });

    // Kinesis metrics
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Kinesis Ingestion',
        left: [
          props.kinesisStream.metricIncomingRecords(),
          props.kinesisStream.metricIncomingBytes(),
        ],
      })
    );

    // Lambda metrics
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'Bronze Layer Lambda',
        left: [
          props.bronzeLambda.metricInvocations(),
          props.bronzeLambda.metricErrors(),
        ],
        right: [
          props.bronzeLambda.metricDuration(),
        ],
      })
    );

    // ECS metrics
    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: 'API Service (ECS)',
        left: [
          props.ecsService.metricCpuUtilization(),
          props.ecsService.metricMemoryUtilization(),
        ],
      })
    );

    // Alarms
    const lambdaErrorAlarm = props.bronzeLambda.metricErrors().createAlarm(this, 'LambdaErrorAlarm', {
      threshold: 10,
      evaluationPeriods: 1,
      alarmDescription: 'Bronze layer Lambda errors',
    });

    const ecsHighCpuAlarm = props.ecsService.metricCpuUtilization().createAlarm(this, 'EcsHighCpuAlarm', {
      threshold: 90,
      evaluationPeriods: 2,
      alarmDescription: 'ECS CPU utilization > 90%',
    });

    // Outputs
    new cdk.CfnOutput(this, 'DashboardUrl', {
      value: `https://console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards:name=${dashboard.dashboardName}`,
      description: 'CloudWatch Dashboard URL',
    });
  }
}
