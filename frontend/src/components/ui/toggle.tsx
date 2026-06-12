import * as React from "react"
import * as TogglePrimitive from "@radix-ui/react-toggle"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const toggleVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors duration-200 hover:bg-[var(--surface-3)] hover:text-[var(--accent-text)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-dim)] focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 data-[state=on]:bg-[rgba(var(--accent-rgb),.12)] data-[state=on]:text-[var(--accent-text)] data-[state=on]:border-[var(--accent-dim)] border border-[var(--border-color)] bg-[var(--surface-2)] text-[var(--text-muted)] active:scale-[0.98]",
  {
    variants: {
      variant: {
        default: "h-9 px-3 gap-2",
        sm: "h-7 px-2.5 text-xs gap-1.5",
        lg: "h-11 px-5 gap-2.5",
      },
      size: {
        default: "h-9 px-3",
        sm: "h-7 px-2.5 text-xs",
        lg: "h-11 px-5",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

const Toggle = React.forwardRef<
  React.ComponentRef<typeof TogglePrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof TogglePrimitive.Root> &
    VariantProps<typeof toggleVariants>
>(({ className, variant, size, ...props }, ref) => (
  <TogglePrimitive.Root
    ref={ref}
    className={cn(toggleVariants({ variant, size, className }))}
    {...props}
  />
))
Toggle.displayName = TogglePrimitive.Root.displayName

export { Toggle, toggleVariants }
