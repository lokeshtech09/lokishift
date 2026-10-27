import type { Metadata, Viewport } from 'next';
// Fonts are bundled with the app (no Google Fonts download at build or run time).
import '@fontsource-variable/inter';
import '@fontsource-variable/plus-jakarta-sans';
import { APP_NAME, APP_TAGLINE } from '@/lib/brand';
import './globals.css';

export const metadata: Metadata = {
  title: { default: APP_NAME, template: `%s · ${APP_NAME}` },
  description: APP_TAGLINE,
  applicationName: APP_NAME,
  // Full-screen when opened from the iPhone home screen.
  appleWebApp: { capable: true, title: APP_NAME, statusBarStyle: 'default' },
};

export const viewport: Viewport = {
  themeColor: '#f3f4f4',
  width: 'device-width',
  initialScale: 1,
  // Content stays clear of the notch / home indicator when installed.
  viewportFit: 'cover',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="min-h-full font-sans antialiased">{children}</body>
    </html>
  );
}
