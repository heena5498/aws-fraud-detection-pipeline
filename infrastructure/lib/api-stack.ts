import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ecsPatterns from 'aws-cdk-lib/aws-ecs-patterns';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';

export interface ApiStackProps extends cdk.StackProps {
  environment: string;
}

export class ApiStack extends cdk.Stack {
  public readonly service: ecs.FargateService;
  public readonly loadBalancer: any;

  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    // VPC for ECS tasks
    const vpc = new ec2.Vpc(this, 'FraudVpc', {
      maxAzs: 2,
      natGateways: 1,  // Cost optimization
    });

    // ECS Cluster
    const cluster = new ecs.Cluster(this, 'FraudCluster', {
      clusterName: `fraud-cluster-${props.environment}`,
      vpc,
      containerInsights: true,
    });

    // ALB + Fargate Service
    const fargateService = new ecsPatterns.ApplicationLoadBalancedFargateService(
      this,
      'FraudApiService',
      {
        cluster,
        serviceName: `fraud-api-${props.environment}`,
        taskImageOptions: {
          image: ecs.ContainerImage.fromAsset('../', {
            file: 'Dockerfile',
          }),
          containerPort: 8000,
          environment: {
            ENVIRONMENT: props.environment,
            BRONZE_BUCKET: `fraud-bronze-${props.environment}`,
            SILVER_BUCKET: `fraud-silver-${props.environment}`,
            GOLD_BUCKET: `fraud-gold-${props.environment}`,
            MODELS_BUCKET: `fraud-models-${props.environment}`,
            ALERTS_TABLE_NAME: `fraud-alerts-${props.environment}`,
            FEEDBACK_TABLE_NAME: `fraud-feedback-${props.environment}`,
            LOG_LEVEL: 'INFO',
          },
          logDriver: ecs.LogDrivers.awsLogs({
            streamPrefix: 'fraud-api',
            logRetention: logs.RetentionDays.ONE_WEEK,
          }),
        },
        cpu: 512,  // 0.5 vCPU
        memoryLimitMiB: 1024,  // 1 GB
        desiredCount: 2,  // Minimum for HA
        publicLoadBalancer: true,
        healthCheckGracePeriod: cdk.Duration.seconds(60),
      }
    );

    // Auto-scaling
    const scaling = fargateService.service.autoScaleTaskCount({
      minCapacity: 2,
      maxCapacity: 10,
    });

    scaling.scaleOnCpuUtilization('CpuScaling', {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });

    scaling.scaleOnMemoryUtilization('MemoryScaling', {
      targetUtilizationPercent: 80,
      scaleInCooldown: cdk.Duration.seconds(60),
      scaleOutCooldown: cdk.Duration.seconds(60),
    });

    // Health check
    fargateService.targetGroup.configureHealthCheck({
      path: '/api/v1/health',
      interval: cdk.Duration.seconds(30),
      timeout: cdk.Duration.seconds(5),
      healthyThresholdCount: 2,
      unhealthyThresholdCount: 3,
    });

    this.service = fargateService.service;
    this.loadBalancer = fargateService.loadBalancer;

    // Outputs
    new cdk.CfnOutput(this, 'LoadBalancerDNS', {
      value: fargateService.loadBalancer.loadBalancerDnsName,
      description: 'DNS name of the load balancer',
    });

    new cdk.CfnOutput(this, 'ApiUrl', {
      value: `http://${fargateService.loadBalancer.loadBalancerDnsName}/api/v1`,
      description: 'Base URL for the API',
    });
  }
}
