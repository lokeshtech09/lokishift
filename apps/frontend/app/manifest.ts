import type { MetadataRoute } from 'next';
import { APP_NAME, APP_TAGLINE } from '@/lib/brand';

/** Lets phones install LokiShift from the browser ("Add to Home Screen"). */
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: APP_NAME,
    short_name: APP_NAME,
    description: APP_TAGLINE,
    start_url: '/dashboard',
    scope: '/',
    display: 'standalone',
    background_color: '#f3f4f4',
    theme_color: '#f3f4f4',
    icons: [
      { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
      { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
      { src: '/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
