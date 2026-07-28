import type { ButtonHTMLAttributes } from "react";

type Variante = "primary" | "ghost";

interface ActionButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variante?: Variante;
}

// A largura fica a cargo de quem usa: no painel os botões ocupam a linha inteira, no
// modal eles dividem o espaço em flex.
const BASE =
  "cursor-pointer rounded-lg border px-3 py-2.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60";

const VARIANTES: Record<Variante, string> = {
  primary: "border-blue-600 bg-blue-600 text-white hover:bg-blue-700 hover:border-blue-700",
  ghost: "border-slate-300 bg-white text-gray-800 hover:bg-slate-50",
};

export function ActionButton({
  variante = "primary",
  className = "",
  type = "button",
  ...props
}: ActionButtonProps) {
  return (
    <button type={type} className={`${BASE} ${VARIANTES[variante]} ${className}`} {...props} />
  );
}
