import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { ButtonModule } from 'primeng/button';

@Component({
  selector: 'app-not-found-page',
  imports: [RouterLink, TranslocoPipe, ButtonModule],
  template: `
    <div class="card">
      <h1>{{ 'notFound.title' | transloco }}</h1>
      <p class="subtitle">{{ 'notFound.body' | transloco }}</p>
      <a class="home-link" routerLink="/tenants">{{ 'notFound.home' | transloco }}</a>
    </div>
  `,
  styleUrl: '../auth/auth-layout.scss',
})
export class NotFoundPage {}
