import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function Svg({ size = 20, children, ...rest }: IconProps & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden focusable="false" {...rest}>
      {children}
    </svg>
  )
}

export const LeafLogo = ({ size = 32 }: { size?: number }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false">
    <path d="M15 27C8 26 3.5 20.5 4 12.5 11 13 15.5 18 15 27Z" fill="var(--brand-700)" />
    <path d="M17 27c-.6-9.5 4.5-17 11-19 .8 10-4 18-11 19Z" fill="var(--brand-400)" />
  </svg>
)

export const IconPlus = (p: IconProps) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>
export const IconHome = (p: IconProps) => <Svg {...p}><path d="M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-4v-6h-6v6H5a1 1 0 0 1-1-1z" /></Svg>
export const IconChat = (p: IconProps) => (
  <Svg {...p}><path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.1A8 8 0 1 1 20 12Z" /></Svg>
)
export const IconBars = (p: IconProps) => <Svg {...p}><path d="M6 20V11M12 20V5M18 20v-6" /></Svg>
export const IconDatabase = (p: IconProps) => (
  <Svg {...p}><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></Svg>
)
export const IconClock = (p: IconProps) => <Svg {...p}><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></Svg>
export const IconSearch = (p: IconProps) => <Svg {...p}><circle cx="11" cy="11" r="6" /><path d="m20 20-4.5-4.5" /></Svg>
export const IconDish = (p: IconProps) => (
  <Svg {...p}><path d="M7 3v8M5 3v5a2 2 0 0 0 4 0V3M7 11v10M16 3c-1.7 1.5-2.5 4-2.5 7H17V3M16 10v11" /></Svg>
)
export const IconCart = (p: IconProps) => (
  <Svg {...p}><path d="M3 4h2l2.2 10.2a1 1 0 0 0 1 .8H18a1 1 0 0 0 1-.8L20.5 8H6" /><circle cx="9" cy="19" r="1.3" /><circle cx="17" cy="19" r="1.3" /></Svg>
)
export const IconBulb = (p: IconProps) => (
  <Svg {...p}><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3Z" /></Svg>
)
export const IconNetwork = (p: IconProps) => (
  <Svg {...p}><circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path d="M11 7 6 17M13 7l5 10M7 19h10" /></Svg>
)
export const IconSpark = (p: IconProps) => (
  <Svg {...p}><path d="M12 3c.6 4.6 3.4 7.4 8 8-4.6.6-7.4 3.4-8 8-.6-4.6-3.4-7.4-8-8 4.6-.6 7.4-3.4 8-8Z" /></Svg>
)
export const IconArrowUp = (p: IconProps) => <Svg {...p}><path d="M12 19V5M6 11l6-6 6 6" /></Svg>
export const IconStop = (p: IconProps) => <Svg {...p}><rect x="7" y="7" width="10" height="10" rx="1.5" /></Svg>
export const IconChevron = (p: IconProps) => <Svg {...p}><path d="m9 6 6 6-6 6" /></Svg>
export const IconMenu = (p: IconProps) => <Svg {...p}><path d="M4 7h16M4 12h16M4 17h16" /></Svg>
export const IconClose = (p: IconProps) => <Svg {...p}><path d="M6 6l12 12M18 6 6 18" /></Svg>
export const IconTable = (p: IconProps) => <Svg {...p}><rect x="4" y="5" width="16" height="14" rx="1.5" /><path d="M4 10h16M10 10v9" /></Svg>

export function SourceIcon({ kind, size }: { kind: string; size?: number }) {
  if (kind === 'meals') return <IconDish size={size} />
  if (kind === 'shopping') return <IconCart size={size} />
  if (kind === 'ml') return <IconNetwork size={size} />
  return <IconDatabase size={size} />
}

export function ActionIcon({ icon, size }: { icon: string; size?: number }) {
  if (icon === 'search') return <IconSearch size={size} />
  if (icon === 'dish') return <IconDish size={size} />
  return <IconBars size={size} />
}
