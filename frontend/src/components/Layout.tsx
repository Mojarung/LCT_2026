import { Outlet } from 'react-router';

import { Footer } from './Footer';
import { TopBar } from './TopBar';

export function Layout() {
  return (
    <>
      <a className="skip" href="#content">
        К содержимому
      </a>
      <TopBar />
      <main id="content">
        <Outlet />
      </main>
      <Footer />
    </>
  );
}
