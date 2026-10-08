import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import { Construct } from 'constructs';

export interface DatabaseStackProps extends cdk.StackProps {
  environment: string;
}

export class DatabaseStack extends cdk.Stack {
  public readonly dedupeTable: dynamodb.Table;
  public readonly alertsTable: dynamodb.Table;
  public readonly feedbackTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    // Deduplication table (exactly-once processing)
    this.dedupeTable = new dynamodb.Table(this, 'DedupeTable', {
      tableName: `fraud-dedupe-${props.environment}`,
      partitionKey: {
        name: 'composite_key',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'expires_at',
      removalPolicy: props.environment === 'prod' 
        ? cdk.RemovalPolicy.RETAIN 
        : cdk.RemovalPolicy.DESTROY,
      pointInTimeRecovery: props.environment === 'prod',
    });

    // Alerts table (high-risk transactions)
    this.alertsTable = new dynamodb.Table(this, 'AlertsTable', {
      tableName: `fraud-alerts-${props.environment}`,
      partitionKey: {
        name: 'alert_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'created_at',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: props.environment === 'prod' 
        ? cdk.RemovalPolicy.RETAIN 
        : cdk.RemovalPolicy.DESTROY,
      pointInTimeRecovery: props.environment === 'prod',
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,  // For downstream processing
    });

    // GSI for querying by status
    this.alertsTable.addGlobalSecondaryIndex({
      indexName: 'status-created_at-index',
      partitionKey: {
        name: 'status',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'created_at',
        type: dynamodb.AttributeType.STRING,
      },
    });

    // Feedback table (analyst decisions)
    this.feedbackTable = new dynamodb.Table(this, 'FeedbackTable', {
      tableName: `fraud-feedback-${props.environment}`,
      partitionKey: {
        name: 'alert_id',
        type: dynamodb.AttributeType.STRING,
      },
      sortKey: {
        name: 'submitted_at',
        type: dynamodb.AttributeType.STRING,
      },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: props.environment === 'prod' 
        ? cdk.RemovalPolicy.RETAIN 
        : cdk.RemovalPolicy.DESTROY,
      pointInTimeRecovery: props.environment === 'prod',
    });

    // Outputs
    new cdk.CfnOutput(this, 'DedupeTableName', {
      value: this.dedupeTable.tableName,
      description: 'DynamoDB table for deduplication',
    });

    new cdk.CfnOutput(this, 'AlertsTableName', {
      value: this.alertsTable.tableName,
      description: 'DynamoDB table for fraud alerts',
    });

    new cdk.CfnOutput(this, 'FeedbackTableName', {
      value: this.feedbackTable.tableName,
      description: 'DynamoDB table for analyst feedback',
    });
  }
}
