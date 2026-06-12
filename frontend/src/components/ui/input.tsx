import * as React from "react"
import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          "flex h-7 w-full rounded-md border border-[var(--border-color)] bg-[var(--surface)] px-2.5 py-1 text-xs text-[var(--text)] placeholder:text-[var(--text-dim)]",
          "transition-colors duration-200",
          "focus-visible:outline-none focus-visible:ring-0 focus-visible:border-[var(--accent-dim)]",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "file:border-0 file:bg-transparent file:text-xs file:font-medium",
          className
        )}
        ref={ref}
        {...props}
      />
    )
  }
)
Input.displayName = "Input"

export { Input }
