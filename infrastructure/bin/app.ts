#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { KinesisStack } from '../lib/kinesis-stack';
import { DatabaseStack } from '../lib/database-stack';
import { ApiStack } from '../lib/api-stack';
import { MonitoringStack } from '../lib/monitoring-stack';

const app = new cdk.App();

const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION || 'us-east-1',
};

const environment = process.env.ENVIRONMENT || 'dev';

// Data ingestion stack
const kinesisStack = new KinesisStack(app, `FraudKinesisStack-${environment}`, {
  env,
  environment,
  description: 'Kinesis data stream and Bronze layer Lambda',
});

// Database stack (DynamoDB tables)
const databaseStack = new DatabaseStack(app, `FraudDatabaseStack-${environment}`, {
  env,
  environment,
  description: 'DynamoDB tables for deduplication, alerts, and feedback',
});

// API stack (ECS Fargate + ALB)
const apiStack = new ApiStack(app, `FraudApiStack-${environment}`, {
  env,
  environment,
  description: 'FastAPI scoring service on ECS Fargate',
});

// Monitoring stack (CloudWatch dashboards and alarms)
const monitoringStack = new MonitoringStack(app, `FraudMonitoringStack-${environment}`, {
  env,
  environment,
  kinesisStream: kinesisStack.stream,
  bronzeLambda: kinesisStack.bronzeLayerFunction,
  ecsService: apiStack.service,
  description: 'CloudWatch dashboards and alarms',
});

app.synth();
