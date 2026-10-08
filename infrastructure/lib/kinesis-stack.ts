import * as cdk from 'aws-cdk-lib';
import * as kinesis from 'aws-cdk-lib/aws-kinesis';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as lambdaEventSources from 'aws-cdk-lib/aws-lambda-event-sources';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import { Construct } from 'constructs';

export interface KinesisStackProps extends cdk.StackProps {
  environment: string;
}

export class KinesisStack extends cdk.Stack {
  public readonly stream: kinesis.Stream;
  public readonly bronzeLayerFunction: lambda.Function;
  public readonly bronzeBucket: s3.Bucket;

  constructor(scope: Construct, id: string, props: KinesisStackProps) {
    super(scope, id, props);

    // S3 buckets for data lake
    this.bronzeBucket = new s3.Bucket(this, 'BronzeBucket', {
      bucketName: `fraud-bronze-${props.environment}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: props.environment === 'prod' 
        ? cdk.RemovalPolicy.RETAIN 
        : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: props.environment !== 'prod',
      lifecycleRules: [
        {
          id: 'TransitionToIA',
          transitions: [
            {
              storageClass: s3.StorageClass.INFREQUENT_ACCESS,
              transitionAfter: cdk.Duration.days(30),
            },
          ],
        },
      ],
    });

    const silverBucket = new s3.Bucket(this, 'SilverBucket', {
      bucketName: `fraud-silver-${props.environment}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: props.environment === 'prod' 
        ? cdk.RemovalPolicy.RETAIN 
        : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: props.environment !== 'prod',
    });

    const goldBucket = new s3.Bucket(this, 'GoldBucket', {
      bucketName: `fraud-gold-${props.environment}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: props.environment === 'prod' 
        ? cdk.RemovalPolicy.RETAIN 
        : cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: props.environment !== 'prod',
    });

    const modelsBucket = new s3.Bucket(this, 'ModelsBucket', {
      bucketName: `fraud-models-${props.environment}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      versioned: true,  // Version control for models
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });

    // Kinesis Data Stream
    this.stream = new kinesis.Stream(this, 'TransactionStream', {
      streamName: `fraud-transactions-${props.environment}`,
      shardCount: 1,  // Scale up in production
      retentionPeriod: cdk.Duration.hours(24),
      encryption: kinesis.StreamEncryption.MANAGED,
    });

    // Bronze Layer Lambda Function
    this.bronzeLayerFunction = new lambda.Function(this, 'BronzeLayerFunction', {
      functionName: `fraud-bronze-${props.environment}`,
      runtime: lambda.Runtime.PYTHON_3_11,
      handler: 'bronze_layer.handler.lambda_handler',
      code: lambda.Code.fromAsset('../src', {
        bundling: {
          image: lambda.Runtime.PYTHON_3_11.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -r . /asset-output'
          ],
        },
      }),
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      environment: {
        BRONZE_BUCKET: this.bronzeBucket.bucketName,
        DEDUPE_TABLE_NAME: `fraud-dedupe-${props.environment}`,
        ENVIRONMENT: props.environment,
        LOG_LEVEL: 'INFO',
      },
      logRetention: logs.RetentionDays.ONE_WEEK,
    });

    // Grant permissions
    this.bronzeBucket.grantWrite(this.bronzeLayerFunction);
    this.stream.grantRead(this.bronzeLayerFunction);

    // Kinesis event source
    this.bronzeLayerFunction.addEventSource(
      new lambdaEventSources.KinesisEventSource(this.stream, {
        startingPosition: lambda.StartingPosition.LATEST,
        batchSize: 100,
        maxBatchingWindow: cdk.Duration.seconds(10),
        retryAttempts: 3,
      })
    );

    // Outputs
    new cdk.CfnOutput(this, 'StreamName', {
      value: this.stream.streamName,
      description: 'Kinesis stream name for transaction ingestion',
    });

    new cdk.CfnOutput(this, 'BronzeBucketName', {
      value: this.bronzeBucket.bucketName,
      description: 'S3 bucket for Bronze layer data',
    });
  }
}
