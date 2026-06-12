import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { SpinnerIosRegular } from "@fluentui/react-icons"

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-0 focus-visible:border-[var(--accent-dim)] disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0 active:scale-[0.98]",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--accent)] text-[var(--text-on-accent)] hover:bg-[var(--accent-h)] shadow-sm",
        destructive:
          "bg-[var(--error)] text-[var(--text-on-accent)] hover:opacity-90 shadow-sm",
        outline:
          "border border-[var(--border-color)] bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--accent-text)] hover:border-[var(--accent-dim)] hover:bg-[var(--surface-3)]",
        secondary:
          "bg-[var(--surface-2)] text-[var(--text)] hover:bg-[var(--surface-3)] border border-[var(--border-color)]",
        ghost:
          "text-[var(--text-muted)] hover:text-[var(--accent-text)] hover:bg-[var(--surface-2)]",
        link: "text-[var(--accent-text)] underline-offset-4 hover:underline",
        primary:
          "bg-[var(--accent)] text-[var(--text-on-accent)] hover:bg-[var(--accent-h)] shadow-sm font-semibold",
        "primary-sm":
          "bg-[var(--accent)] text-[var(--text-on-accent)] hover:bg-[var(--accent-h)] border-[var(--accent)]",
      },
      size: {
        default: "h-7 rounded-md px-2.5 text-xs",
        sm: "h-7 rounded-md px-2.5 text-xs",
        lg: "h-7 rounded-md px-2.5 text-xs",
        icon: "h-7 w-7",
        "icon-sm": "h-7 w-7",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
  loading?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        disabled={disabled || loading}
        {...props}
      >
        {asChild
          ? children
          : <>{loading && <SpinnerIosRegular className="animate-spin" />}{children}</>
        }
      </Comp>
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
