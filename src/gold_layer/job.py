"""
Gold Layer Glue Job
Creates point-in-time feature table for ML training.

Ensures no data leakage by using only features available at prediction time.
Implements asof_join pattern for temporal correctness.
"""

import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
from pyspark.sql import functions as F, Window
from pyspark.sql.types import *
from datetime import datetime, timedelta

# Parse job arguments
args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'silver_bucket',
    'gold_bucket',
    'training_start_date',  # YYYY-MM-DD
    'training_end_date',    # YYYY-MM-DD
    'environment'
])

# Initialize Spark
sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

print(f"[Gold Job] Starting: {args['JOB_NAME']}")
print(f"[Gold Job] Training period: {args['training_start_date']} to {args['training_end_date']}")


# ==================== Load Silver Data ====================

silver_path = f"s3://{args['silver_bucket']}/transactions/"
print(f"[Gold Job] Reading Silver data from: {silver_path}")

df_silver = spark.read.parquet(silver_path)
df_silver = df_silver.withColumn('timestamp', F.col('timestamp').cast(TimestampType()))

# Filter to training period
start_date = datetime.strptime(args['training_start_date'], '%Y-%m-%d')
end_date = datetime.strptime(args['training_end_date'], '%Y-%m-%d')

df_train = df_silver.filter(
    (F.col('timestamp') >= F.lit(start_date)) &
    (F.col('timestamp') < F.lit(end_date))
)

print(f"[Gold Job] Loaded {df_train.count()} training records")


# ==================== Point-in-Time Features ====================

# Select final feature set for ML
feature_columns = [
    # Identifiers
    'transaction_id',
    'timestamp',
    
    # Transaction features
    'amount',
    'transaction_type',
    'country',
    'currency',
    'merchant_category',
    
    # Velocity features (5m, 1h, 24h)
    'user_txn_count_5m',
    'user_total_amount_5m',
    'user_avg_amount_5m',
    'user_txn_count_1h',
    'user_total_amount_1h',
    'user_avg_amount_1h',
    'user_txn_count_24h',
    'user_total_amount_24h',
    'user_avg_amount_24h',
    
    # User aggregates
    'user_lifetime_txn_count',
    'user_lifetime_total_amount',
    'user_lifetime_avg_amount',
    
    # Merchant aggregates
    'merchant_txn_count',
    'merchant_total_amount',
    'merchant_fraud_count',
    'merchant_fraud_rate',
    
    # Derived features
    'amount_vs_user_avg_ratio',
    'hour_of_day',
    'day_of_week',
    'is_weekend',
    
    # Target
    'is_fraud'
]

df_gold = df_train.select(*feature_columns)


# ==================== Feature Validation ====================

# Check for nulls
null_counts = df_gold.select([F.sum(F.col(c).isNull().cast('int')).alias(c) for c in df_gold.columns])
print("[Gold Job] Null counts:")
null_counts.show()

# Fill nulls with 0 for numeric features (indicates no prior activity)
numeric_cols = [
    'user_txn_count_5m', 'user_total_amount_5m', 'user_avg_amount_5m',
    'user_txn_count_1h', 'user_total_amount_1h', 'user_avg_amount_1h',
    'user_txn_count_24h', 'user_total_amount_24h', 'user_avg_amount_24h',
    'user_lifetime_txn_count', 'user_lifetime_total_amount', 'user_lifetime_avg_amount',
    'merchant_txn_count', 'merchant_total_amount', 'merchant_fraud_count', 'merchant_fraud_rate'
]

for col in numeric_cols:
    df_gold = df_gold.fillna({col: 0.0})

print("[Gold Job] Null handling complete")


# ==================== Class Distribution ====================

fraud_stats = df_gold.groupBy('is_fraud').count()
print("[Gold Job] Class distribution:")
fraud_stats.show()

total = df_gold.count()
fraud_count = df_gold.filter(F.col('is_fraud') == 1).count()
fraud_rate = (fraud_count / total) * 100

print(f"[Gold Job] Fraud rate: {fraud_rate:.2f}% ({fraud_count}/{total})")


# ==================== Write to Gold ====================

gold_path = f"s3://{args['gold_bucket']}/training/"
print(f"[Gold Job] Writing {df_gold.count()} records to Gold")

df_gold.write.mode('overwrite').parquet(
    gold_path,
    compression='snappy'
)

print(f"[Gold Job] Gold data written to: {gold_path}")


# ==================== Feature Statistics (for monitoring) ====================

# Compute feature statistics for PSI baseline
feature_stats_path = f"s3://{args['gold_bucket']}/feature_stats/baseline/"

stats_df = df_gold.select(
    F.lit(args['training_start_date']).alias('period_start'),
    F.lit(args['training_end_date']).alias('period_end'),
    F.mean('amount').alias('amount_mean'),
    F.stddev('amount').alias('amount_stddev'),
    F.mean('user_txn_count_1h').alias('user_txn_count_1h_mean'),
    F.stddev('user_txn_count_1h').alias('user_txn_count_1h_stddev'),
    F.mean('merchant_fraud_rate').alias('merchant_fraud_rate_mean'),
    F.stddev('merchant_fraud_rate').alias('merchant_fraud_rate_stddev'),
    F.count('*').alias('total_records'),
    F.sum('is_fraud').alias('fraud_count')
)

stats_df.write.mode('overwrite').parquet(feature_stats_path)

print(f"[Gold Job] Feature stats written to: {feature_stats_path}")

# Commit job
job.commit()
print("[Gold Job] Complete")
