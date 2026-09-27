type ButtonProps = {
  children: string;
};

export function Button({ children }: ButtonProps) {
  return (
    <button
      type="button"
      className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white"
    >
      {children}
    </button>
  );
}
