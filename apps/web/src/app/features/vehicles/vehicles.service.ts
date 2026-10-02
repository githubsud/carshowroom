import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { environment } from '../../../environments/environment';
import {
  DocumentType,
  Location,
  LocationInput,
  Preview,
  PurchaseInput,
  PurchasePosting,
  SearchResult,
  SellerPaymentInput,
  SellerPaymentPosting,
  UploadTicket,
  Vehicle,
  VehicleDocument,
  VehicleExpenseInput,
  VehicleExpensePosting,
  VehicleInput,
  VehiclePage,
  VehicleStatus,
  VehicleUpdate,
} from '../../core/api/api.models';
import { idempotent, Query, toParams } from '../../shared/http-params';

export interface VehicleFilters {
  status?: readonly VehicleStatus[];
  q?: string;
  make?: string;
  year?: number | null;
  location_id?: string | null;
  aging?: string | null;
  sort?: string;
  page?: number;
  page_size?: number;
}

/** Calls to the vehicle endpoints (docs/API.md §3.4). */
@Injectable({ providedIn: 'root' })
export class VehiclesService {
  private readonly http = inject(HttpClient);
  private readonly base = environment.apiBaseUrl;

  list(filters: VehicleFilters): Promise<VehiclePage> {
    return firstValueFrom(
      this.http.get<VehiclePage>(`${this.base}/vehicles`, { params: toParams(filters as Query) }),
    );
  }

  get(id: string): Promise<Vehicle> {
    return firstValueFrom(this.http.get<Vehicle>(`${this.base}/vehicles/${id}`));
  }

  create(body: VehicleInput): Promise<Vehicle> {
    return firstValueFrom(this.http.post<Vehicle>(`${this.base}/vehicles`, body));
  }

  update(id: string, body: VehicleUpdate): Promise<Vehicle> {
    return firstValueFrom(this.http.patch<Vehicle>(`${this.base}/vehicles/${id}`, body));
  }

  setStatus(id: string, status: VehicleStatus, reason?: string | null): Promise<Vehicle> {
    return firstValueFrom(this.http.post<Vehicle>(`${this.base}/vehicles/${id}/status`, { status, reason: reason || null }));
  }

  move(id: string, locationId: string, reason?: string | null): Promise<Vehicle> {
    return firstValueFrom(
      this.http.post<Vehicle>(`${this.base}/vehicles/${id}/move`, { location_id: locationId, reason: reason || null }),
    );
  }

  search(q: string): Promise<SearchResult> {
    return firstValueFrom(this.http.get<SearchResult>(`${this.base}/search`, { params: toParams({ q }) }));
  }

  // --- Locations ---------------------------------------------------------------------
  locations(includeArchived = false): Promise<Location[]> {
    return firstValueFrom(
      this.http.get<Location[]>(`${this.base}/locations`, { params: toParams({ include_archived: includeArchived }) }),
    );
  }

  createLocation(body: LocationInput): Promise<Location> {
    return firstValueFrom(this.http.post<Location>(`${this.base}/locations`, body));
  }

  updateLocation(id: string, body: { archived?: boolean; is_default?: boolean }): Promise<Location> {
    return firstValueFrom(this.http.patch<Location>(`${this.base}/locations/${id}`, body));
  }

  // --- Purchase, seller payments, expenses: preview then post -------------------------
  previewPurchase(id: string, body: PurchaseInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/vehicles/${id}/purchase/preview`, body));
  }

  recordPurchase(id: string, body: PurchaseInput, key: string): Promise<PurchasePosting> {
    return firstValueFrom(this.http.post<PurchasePosting>(`${this.base}/vehicles/${id}/purchase`, body, idempotent(key)));
  }

  previewSellerPayment(id: string, body: SellerPaymentInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/vehicles/${id}/seller-payments/preview`, body));
  }

  recordSellerPayment(id: string, body: SellerPaymentInput, key: string): Promise<SellerPaymentPosting> {
    return firstValueFrom(
      this.http.post<SellerPaymentPosting>(`${this.base}/vehicles/${id}/seller-payments`, body, idempotent(key)),
    );
  }

  previewExpense(id: string, body: VehicleExpenseInput): Promise<Preview> {
    return firstValueFrom(this.http.post<Preview>(`${this.base}/vehicles/${id}/expenses/preview`, body));
  }

  recordExpense(id: string, body: VehicleExpenseInput, key: string): Promise<VehicleExpensePosting> {
    return firstValueFrom(
      this.http.post<VehicleExpensePosting>(`${this.base}/vehicles/${id}/expenses`, body, idempotent(key)),
    );
  }

  // --- Photos and documents (signed URLs, D-15) ---------------------------------------------
  async uploadPhoto(vehicleId: string, file: Blob): Promise<void> {
    const ticket = await firstValueFrom(
      this.http.post<UploadTicket>(`${this.base}/vehicles/${vehicleId}/media/upload-url`, {
        content_type: file.type,
        size_bytes: file.size,
      }),
    );
    await this.put(ticket.upload_url, file);
    await firstValueFrom(
      this.http.post(`${this.base}/vehicles/${vehicleId}/media`, {
        storage_path: ticket.storage_path,
        content_type: file.type,
        size_bytes: file.size,
      }),
    );
  }

  removePhoto(vehicleId: string, mediaId: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`${this.base}/vehicles/${vehicleId}/media/${mediaId}`));
  }

  async uploadDocument(vehicleId: string, docType: DocumentType, file: File): Promise<VehicleDocument> {
    const meta = {
      entity_type: 'VEHICLE' as const,
      entity_id: vehicleId,
      doc_type: docType,
      file_name: file.name,
      content_type: file.type,
      size_bytes: file.size,
    };
    const ticket = await firstValueFrom(this.http.post<UploadTicket>(`${this.base}/documents/upload-url`, meta));
    await this.put(ticket.upload_url, file);
    return firstValueFrom(
      this.http.post<VehicleDocument>(`${this.base}/documents`, { ...meta, storage_path: ticket.storage_path }),
    );
  }

  documentUrl(documentId: string): Promise<{ url: string }> {
    return firstValueFrom(this.http.get<{ url: string }>(`${this.base}/documents/${documentId}/url`));
  }

  removeDocument(documentId: string): Promise<unknown> {
    return firstValueFrom(this.http.delete(`${this.base}/documents/${documentId}`));
  }

  /** The signed URL is for Supabase Storage directly, not our API (no tenant headers). */
  private async put(url: string, file: Blob): Promise<void> {
    const response = await fetch(url, { method: 'PUT', body: file, headers: { 'Content-Type': file.type } });
    if (!response.ok) {
      throw new Error(`upload failed: ${response.status}`);
    }
  }
}
