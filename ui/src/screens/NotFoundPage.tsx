import { useLocation } from 'react-router'
import { LinkButton } from '../components/Button'
import { EmptyState } from '../components/EmptyState'
import { PageHeader } from '../components/PageHeader'

/** 404 inside the shell (STANDARD law 5): nav intact, a way back. */
export function NotFoundPage() {
  const loc = useLocation()
  return (
    <>
      <PageHeader eyebrow="Not found" title="This page does not exist" />
      <EmptyState glyph="∅" title="Nothing lives at this address" reason={<span className="font-mono text-xs">{loc.pathname}</span>} action={<LinkButton variant="filled" to="/repos">Back to repos</LinkButton>} />
    </>
  )
}

export default NotFoundPage
