import React, { useState, useEffect } from 'react';
import axios from 'axios';
import {
  Container,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Paper,
  Chip,
  Button,
  CircularProgress,
  Alert
} from '@mui/material';

interface Alert {
  alert_id: string;
  transaction_id: string;
  fraud_probability: number;
  amount: number;
  user_id: string;
  merchant_id: string;
  created_at: string;
  status: string;
}

const API_BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

export const AlertsList: React.FC = () => {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchAlerts();
  }, []);

  const fetchAlerts = async () => {
    setLoading(true);
    setError(null);

    try {
      const response = await axios.get<Alert[]>(`${API_BASE_URL}/api/v1/alerts`, {
        params: { limit: 50 }
      });
      setAlerts(response.data);
    } catch (err) {
      setError('Failed to fetch alerts. Please try again.');
      console.error('Error fetching alerts:', err);
    } finally {
      setLoading(false);
    }
  };

  const getRiskColor = (probability: number): 'error' | 'warning' | 'success' => {
    if (probability >= 0.7) return 'error';
    if (probability >= 0.3) return 'warning';
    return 'success';
  };

  const getStatusColor = (status: string): 'default' | 'primary' | 'success' | 'error' => {
    switch (status) {
      case 'pending': return 'default';
      case 'reviewed': return 'primary';
      case 'confirmed_fraud': return 'error';
      case 'confirmed_legitimate': return 'success';
      default: return 'default';
    }
  };

  if (loading) {
    return (
      <Container sx={{ display: 'flex', justifyContent: 'center', mt: 4 }}>
        <CircularProgress />
      </Container>
    );
  }

  if (error) {
    return (
      <Container sx={{ mt: 4 }}>
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ mt: 4, mb: 4 }}>
      <Typography variant="h4" gutterBottom>
        Fraud Alerts
      </Typography>
      
      <Button 
        variant="outlined" 
        onClick={fetchAlerts}
        sx={{ mb: 2 }}
      >
        Refresh
      </Button>

      <TableContainer component={Paper}>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Alert ID</TableCell>
              <TableCell>Transaction ID</TableCell>
              <TableCell align="right">Amount</TableCell>
              <TableCell align="center">Fraud Probability</TableCell>
              <TableCell>Created At</TableCell>
              <TableCell align="center">Status</TableCell>
              <TableCell align="center">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {alerts.map((alert) => (
              <TableRow key={alert.alert_id}>
                <TableCell>{alert.alert_id}</TableCell>
                <TableCell>{alert.transaction_id}</TableCell>
                <TableCell align="right">
                  ${parseFloat(alert.amount.toString()).toFixed(2)}
                </TableCell>
                <TableCell align="center">
                  <Chip 
                    label={`${(alert.fraud_probability * 100).toFixed(1)}%`}
                    color={getRiskColor(alert.fraud_probability)}
                    size="small"
                  />
                </TableCell>
                <TableCell>
                  {new Date(alert.created_at).toLocaleString()}
                </TableCell>
                <TableCell align="center">
                  <Chip 
                    label={alert.status.replace('_', ' ')}
                    color={getStatusColor(alert.status)}
                    size="small"
                  />
                </TableCell>
                <TableCell align="center">
                  <Button 
                    size="small" 
                    variant="text"
                    href={`/alerts/${alert.alert_id}`}
                  >
                    Details
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>

      {alerts.length === 0 && (
        <Alert severity="info" sx={{ mt: 2 }}>
          No fraud alerts found.
        </Alert>
      )}
    </Container>
  );
};

export default AlertsList;
