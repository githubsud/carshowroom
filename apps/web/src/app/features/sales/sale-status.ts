import { Sale } from '../../core/api/api.models';

export function saleSeverity(status: Sale['status']): 'success' | 'secondary' | 'danger' {
  return status === 'POSTED' ? 'success' : status === 'CANCELLED' ? 'danger' : 'secondary';
}
