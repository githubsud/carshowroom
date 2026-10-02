import { VehicleStatus } from '../../core/api/api.models';

type Severity = 'success' | 'info' | 'warn' | 'danger' | 'secondary' | 'contrast';

/** Tag colour per lifecycle status. */
export function statusSeverity(status: VehicleStatus): Severity {
  switch (status) {
    case 'AVAILABLE':
      return 'success';
    case 'RESERVED':
      return 'warn';
    case 'SOLD':
    case 'DELIVERED':
      return 'info';
    case 'IN_PREPARATION':
    case 'AT_OTHER_SHOWROOM':
      return 'contrast';
    default:
      return 'secondary';
  }
}
