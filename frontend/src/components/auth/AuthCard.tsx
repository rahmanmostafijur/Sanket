import type { ReactNode } from 'react'
import { Link } from 'react-router'
import { Logo } from '@/components/brand/Logo'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'

interface AuthCardProps {
  title: string
  description: string
  children: ReactNode
  footer: ReactNode
}

/** The centred card the sign-in and sign-up pages share. */
export function AuthCard({ title, description, children, footer }: AuthCardProps) {
  return (
    <main className="grid min-h-dvh place-items-center bg-bg px-4 py-10">
      <div className="w-full max-w-sm space-y-4">
        <Card className="w-full gap-6 [--card-spacing:--spacing(6)]">
          <CardHeader className="justify-items-center gap-4 text-center">
            <Link to="/" aria-label="Sanket home">
              <Logo />
            </Link>
            <CardTitle className="text-xl font-semibold text-fg">{title}</CardTitle>
            <CardDescription className="text-muted">{description}</CardDescription>
          </CardHeader>
          <CardContent>{children}</CardContent>
          <CardFooter className="justify-center border-t border-line text-[13.5px] text-muted">{footer}</CardFooter>
        </Card>
        <p className="text-center text-[13px] text-subtle">
          <Link to="/" className="hover:text-fg">Browse jobs without an account</Link>
        </p>
      </div>
    </main>
  )
}

/** A form-level problem, announced to screen readers. */
export function FormError({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-[10px] border border-danger/40 bg-danger/10 px-3.5 py-2.5 text-[13px] leading-relaxed text-danger">
      {children}
    </div>
  )
}
