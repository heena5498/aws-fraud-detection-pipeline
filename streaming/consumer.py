"""
Kafka Consumer - Real-Time Fraud Detection
===========================================
Consumes transactions from Kafka and scores them in real-time
"""

import json
import yaml
import requests
from kafka import KafkaConsumer
from loguru import logger
from datetime import datetime
from typing import Dict
import pandas as pd
from pathlib import Path


class FraudDetectionConsumer:
    """Consume transactions and score them for fraud."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize Kafka consumer."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        kafka_config = self.config['kafka']
        
        # Initialize Kafka consumer
        self.consumer = KafkaConsumer(
            kafka_config['topics']['raw_transactions'],
            bootstrap_servers=kafka_config['bootstrap_servers'],
            group_id=kafka_config['consumer']['group_id'],
            auto_offset_reset=kafka_config['consumer']['auto_offset_reset'],
            enable_auto_commit=kafka_config['consumer']['enable_auto_commit'],
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )
        
        # API endpoint for predictions
        self.api_url = f"http://{self.config['api']['host']}:{self.config['api']['port']}/predict"
        
        # Initialize metrics
        self.metrics = {
            'total_processed': 0,
            'fraud_detected': 0,
            'high_risk': 0,
            'api_errors': 0,
            'true_positives': 0,
            'false_positives': 0,
            'true_negatives': 0,
            'false_negatives': 0
        }
        
        # Alerts storage
        self.alerts = []
        self.alerts_path = Path("data/alerts")
        self.alerts_path.mkdir(parents=True, exist_ok=True)
        
        logger.info("Fraud Detection Consumer initialized")
        logger.info(f"Consuming from: {kafka_config['topics']['raw_transactions']}")
        logger.info(f"API endpoint: {self.api_url}")
    
    def score_transaction(self, transaction: Dict) -> Dict:
        """Score transaction using fraud detection API."""
        try:
            # Call API
            response = requests.post(
                self.api_url,
                json=transaction,
                timeout=self.config['api']['prediction_timeout']
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"API error: {response.status_code} - {response.text}")
                self.metrics['api_errors'] += 1
                return None
        
        except Exception as e:
            logger.error(f"Failed to score transaction: {str(e)}")
            self.metrics['api_errors'] += 1
            return None
    
    def handle_prediction(self, transaction: Dict, prediction: Dict):
        """Handle fraud prediction and create alerts."""
        self.metrics['total_processed'] += 1
        
        # Extract prediction details
        fraud_prob = prediction['fraud_probability']
        is_fraud_pred = prediction['is_fraud']
        risk_level = prediction['risk_level']
        
        # Ground truth (if available)
        actual_fraud = transaction.get('is_fraud', None)
        
        # Update fraud detection metrics
        if is_fraud_pred:
            self.metrics['fraud_detected'] += 1
        
        if risk_level == 'HIGH':
            self.metrics['high_risk'] += 1
        
        # Update confusion matrix (if ground truth available)
        if actual_fraud is not None:
            if is_fraud_pred and actual_fraud:
                self.metrics['true_positives'] += 1
            elif is_fraud_pred and not actual_fraud:
                self.metrics['false_positives'] += 1
            elif not is_fraud_pred and actual_fraud:
                self.metrics['false_negatives'] += 1
            else:
                self.metrics['true_negatives'] += 1
        
        # Log high-risk transactions
        if risk_level in ['HIGH', 'MEDIUM']:
            logger.warning(
                f"⚠️  FRAUD ALERT | "
                f"ID: {transaction['transaction_id']} | "
                f"Prob: {fraud_prob:.2%} | "
                f"Risk: {risk_level} | "
                f"Amount: ${transaction['amount']:.2f}"
            )
            
            # Store alert
            alert = {
                **transaction,
                **prediction,
                'alert_timestamp': datetime.now().isoformat()
            }
            self.alerts.append(alert)
        
        # Log normal transactions (debug level)
        else:
            logger.debug(
                f"✓ Transaction {transaction['transaction_id']} | "
                f"Prob: {fraud_prob:.2%} | Risk: {risk_level}"
            )
    
    def save_alerts(self):
        """Save fraud alerts to file."""
        if not self.alerts:
            return
        
        # Convert to DataFrame
        df = pd.DataFrame(self.alerts)
        
        # Save to CSV
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        alerts_file = self.alerts_path / f"fraud_alerts_{timestamp}.csv"
        df.to_csv(alerts_file, index=False)
        
        logger.info(f"✓ Saved {len(self.alerts)} alerts to {alerts_file}")
        self.alerts = []  # Clear alerts
    
    def print_metrics(self):
        """Print current metrics."""
        m = self.metrics
        
        logger.info("=" * 60)
        logger.info("REAL-TIME METRICS")
        logger.info("=" * 60)
        logger.info(f"Total Processed: {m['total_processed']:,}")
        logger.info(f"Fraud Detected:  {m['fraud_detected']:,} ({m['fraud_detected']/max(m['total_processed'],1)*100:.1f}%)")
        logger.info(f"High Risk:       {m['high_risk']:,}")
        logger.info(f"API Errors:      {m['api_errors']:,}")
        
        # Confusion matrix (if ground truth available)
        if m['true_positives'] + m['false_positives'] > 0:
            precision = m['true_positives'] / (m['true_positives'] + m['false_positives'])
            recall = m['true_positives'] / (m['true_positives'] + m['false_negatives'])
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            
            logger.info("-" * 60)
            logger.info("MODEL PERFORMANCE (Real-time)")
            logger.info(f"Precision: {precision:.2%}")
            logger.info(f"Recall:    {recall:.2%}")
            logger.info(f"F1-Score:  {f1:.2%}")
            logger.info(f"TP: {m['true_positives']:,} | FP: {m['false_positives']:,}")
            logger.info(f"TN: {m['true_negatives']:,} | FN: {m['false_negatives']:,}")
        
        logger.info("=" * 60)
    
    def consume_and_score(self):
        """Main consumer loop - consume and score transactions."""
        logger.info("=" * 60)
        logger.info("STARTING REAL-TIME FRAUD DETECTION")
        logger.info("=" * 60)
        logger.info("Waiting for transactions...")
        logger.info("Press Ctrl+C to stop")
        logger.info("=" * 60)
        
        try:
            for message in self.consumer:
                transaction = message.value
                
                # Score transaction
                prediction = self.score_transaction(transaction)
                
                if prediction:
                    self.handle_prediction(transaction, prediction)
                
                # Print metrics every 100 transactions
                if self.metrics['total_processed'] % 100 == 0:
                    self.print_metrics()
                
                # Save alerts every 50 alerts
                if len(self.alerts) >= 50:
                    self.save_alerts()
        
        except KeyboardInterrupt:
            logger.info("\nStopped by user")
        
        finally:
            # Final metrics
            self.print_metrics()
            
            # Save remaining alerts
            if self.alerts:
                self.save_alerts()
            
            self.consumer.close()
            logger.info("Consumer closed")


def main():
    """Run the fraud detection consumer."""
    consumer = FraudDetectionConsumer()
    consumer.consume_and_score()


if __name__ == "__main__":
    main()
