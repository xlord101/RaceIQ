import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'RaceIQ — From telemetry to race decisions',
  description: 'An explainable race-engineering intelligence system for Haas.',
  generator: 'v0.app',
}

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#050505',
  userScalable: true,
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return   <html lang="en" className="bg-background"><body className="antialiased">{children}{process.env.NODE_ENV === 'production' && process.env.VERCEL === '1' && <Analytics />}</body></html>
}
