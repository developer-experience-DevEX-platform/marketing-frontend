import type { ReactNode } from 'react';

type PageProps = {
  title: string;
  children: ReactNode;
};

export function Page({ title, children }: PageProps) {
  return (
    <main className="mx-auto max-w-3xl p-8">
      <h1 className="text-3xl font-semibold text-slate-900">{title}</h1>
      <div className="mt-6 space-y-4 text-slate-700">{children}</div>
    </main>
  );
}
