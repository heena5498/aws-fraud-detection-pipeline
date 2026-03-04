"""
Kafka Producer - Simulate Real-Time Transactions
=================================================
Simulates streaming transaction data to Kafka
"""

import json
import time
import yaml
import numpy as np
from kafka import KafkaProducer
from datetime import datetime, timedelta
from loguru import logger
import pandas as pd
from pathlib import Path


class TransactionProducer:
    """Produce simulated transactions to Kafka."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize Kafka producer."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        kafka_config = self.config['kafka']
        
        # Initialize Kafka producer
        self.producer = KafkaProducer(
            bootstrap_servers=kafka_config['bootstrap_servers'],
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            compression_type=kafka_config['producer']['compression_type']
        )
        
        self.topic = kafka_config['topics']['raw_transactions']
        
        logger.info(f"Kafka Producer initialized")
        logger.info(f"Topic: {self.topic}")
        logger.info(f"Bootstrap servers: {kafka_config['bootstrap_servers']}")
    
    def generate_transaction(self) -> dict:
        """Generate a single synthetic transaction."""
        # Generate realistic transaction
        transaction_id = f"txn_{datetime.now().strftime('%Y%m%d%H%M%S')}_{np.random.randint(10000, 99999)}"
        
        # User and merchant
        user_id = f"user_{np.random.randint(1, 10001)}"
        merchant_id = f"merchant_{np.random.randint(1, 5001)}"
        
        # Amount (log-normal distribution)
        amount = float(np.random.lognormal(mean=4, sigma=1.5))
        amount = round(np.clip(amount, 1, 10000), 2)
        
        # Merchant category
        categories = ['retail', 'grocery', 'restaurant', 'gas_station', 'online', 'entertainment', 'travel']
        merchant_category = np.random.choice(categories)
        
        # Country
        countries = ['US', 'UK', 'CA', 'FR', 'DE']
        country = np.random.choice(countries, p=[0.55, 0.15, 0.12, 0.10, 0.08])
        
        # Determine if fraud (2% probability)
        is_fraud = int(np.random.random() < 0.02)
        
        # Make fraud transactions look suspicious
        if is_fraud:
            amount *= np.random.uniform(2, 5)  # Higher amount
            merchant_category = np.random.choice(['online', 'travel'])  # Risky categories
        
        transaction = {
            'transaction_id': transaction_id,
            'timestamp': datetime.now().isoformat(),
            'user_id': user_id,
            'merchant_id': merchant_id,
            'amount': round(amount, 2),
            'merchant_category': merchant_category,
            'country': country,
            'is_fraud': is_fraud  # Ground truth (in real scenario, this wouldn't be known)
        }
        
        return transaction
    
    def send_transaction(self, transaction: dict):
        """Send transaction to Kafka topic."""
        try:
            future = self.producer.send(self.topic, value=transaction)
            # Block until message is sent
            record_metadata = future.get(timeout=10)
            
            logger.debug(
                f"Sent: {transaction['transaction_id']} | "
                f"Amount: ${transaction['amount']:.2f} | "
                f"Fraud: {transaction['is_fraud']}"
            )
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to send transaction: {str(e)}")
            return False
    
    def produce_stream(self, rate: int = 10, duration: int = 60):
        """
        Produce streaming transactions.
        
        Args:
            rate: Transactions per second
            duration: Duration in seconds (0 for infinite)
        """
        logger.info("=" * 60)
        logger.info("STARTING TRANSACTION STREAM")
        logger.info("=" * 60)
        logger.info(f"Rate: {rate} transactions/second")
        logger.info(f"Duration: {duration}s ({'infinite' if duration == 0 else duration}s)")
        logger.info(f"Topic: {self.topic}")
        logger.info("=" * 60)
        
        start_time = time.time()
        count = 0
        fraud_count = 0
        
        try:
            while True:
                # Generate and send transaction
                txn = self.generate_transaction()
                success = self.send_transaction(txn)
                
                if success:
                    count += 1
                    if txn['is_fraud']:
                        fraud_count += 1
                
                # Log progress every 100 transactions
                if count % 100 == 0:
                    elapsed = time.time() - start_time
                    logger.info(
                        f"Sent {count:,} transactions | "
                        f"Fraud: {fraud_count} ({fraud_count/count*100:.1f}%) | "
                        f"Elapsed: {elapsed:.1f}s"
                    )
                
                # Check duration
                if duration > 0 and (time.time() - start_time) >= duration:
                    break
                
                # Sleep to maintain rate
                time.sleep(1.0 / rate)
        
        except KeyboardInterrupt:
            logger.info("\nStopped by user")
        
        finally:
            self.producer.flush()
            self.producer.close()
            
            elapsed = time.time() - start_time
            logger.info("=" * 60)
            logger.info("STREAM STOPPED")
            logger.info(f"Total sent: {count:,} transactions")
            logger.info(f"Fraud: {fraud_count} ({fraud_count/count*100:.1f}%)")
            logger.info(f"Duration: {elapsed:.1f}s")
            logger.info(f"Avg rate: {count/elapsed:.1f} txn/s")
            logger.info("=" * 60)
    
    def produce_from_file(self, file_path: str, rate: int = 10):
        """
        Produce transactions from a CSV file.
        Useful for replaying historical data.
        """
        logger.info(f"Loading transactions from {file_path}")
        
        df = pd.read_csv(file_path)
        logger.info(f"Loaded {len(df):,} transactions")
        
        count = 0
        for _, row in df.iterrows():
            txn = row.to_dict()
            
            # Ensure timestamp is current
            txn['timestamp'] = datetime.now().isoformat()
            
            self.send_transaction(txn)
            count += 1
            
            if count % 100 == 0:
                logger.info(f"Sent {count:,} / {len(df):,} transactions")
            
            time.sleep(1.0 / rate)
        
        self.producer.flush()
        self.producer.close()
        logger.info(f"✓ Sent all {count:,} transactions")


def main():
    """Run the transaction producer."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Kafka Transaction Producer")
    parser.add_argument('--rate', type=int, default=10, help='Transactions per second')
    parser.add_argument('--duration', type=int, default=60, help='Duration in seconds (0 for infinite)')
    parser.add_argument('--file', type=str, help='CSV file to replay (optional)')
    
    args = parser.parse_args()
    
    producer = TransactionProducer()
    
    if args.file:
        producer.produce_from_file(args.file, rate=args.rate)
    else:
        producer.produce_stream(rate=args.rate, duration=args.duration)


if __name__ == "__main__":
    main()
