import { useMeta } from '../api/queries';

export function Footer() {
  const meta = useMeta();
  return (
    <footer className="footer">
      <span className="mono">green{meta.data ? ` ${meta.data.version}` : ''}</span>
    </footer>
  );
}
