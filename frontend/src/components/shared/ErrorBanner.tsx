export function ErrorBanner({ error }: { error: string }) {
  if (!error) return null;
  return (
    <div className="p-4 bg-red-500/10 border border-red-500/30 text-red-500 rounded-xl text-sm font-medium flex items-center">
      <svg className="w-5 h-5 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
      {error}
    </div>
  );
}
