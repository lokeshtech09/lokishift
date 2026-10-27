import { ActivityProvider } from '@/components/activity-provider';
import { Sidebar } from '@/components/sidebar';

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ActivityProvider>
      <div className="lg:flex">
        <Sidebar />
        <main className="min-w-0 flex-1 px-4 py-8 sm:px-8 lg:px-12 lg:py-12">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </ActivityProvider>
  );
}
