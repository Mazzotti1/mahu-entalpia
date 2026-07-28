interface ProgressBarProps {
  /** 0..100 para progresso real; `null` quando não há fração conhecida. */
  valor: number | null;
  rotulo: string;
  /** Mostrado à direita do rótulo: porcentagem no envio, tempo decorrido no processamento. */
  detalhe?: string;
}

export function ProgressBar({ valor, rotulo, detalhe }: ProgressBarProps) {
  const indeterminada = valor == null;

  return (
    <div className="mt-2">
      <div className="mb-1 flex items-baseline justify-between gap-2 text-xs text-slate-600">
        <span>{rotulo}</span>
        {detalhe && <span className="tabular-nums">{detalhe}</span>}
      </div>
      <div
        role="progressbar"
        aria-label={rotulo}
        aria-valuemin={indeterminada ? undefined : 0}
        aria-valuemax={indeterminada ? undefined : 100}
        aria-valuenow={indeterminada ? undefined : valor}
        className="h-1.5 w-full overflow-hidden rounded-full bg-slate-200"
      >
        {indeterminada ? (
          <div className="barra-indeterminada h-full w-1/4 rounded-full bg-blue-600" />
        ) : (
          <div
            className="h-full rounded-full bg-blue-600 transition-[width] duration-200 ease-out"
            style={{ width: `${Math.min(100, Math.max(0, valor))}%` }}
          />
        )}
      </div>
    </div>
  );
}
