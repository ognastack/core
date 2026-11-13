import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Cookie key used by OgnaClient
const COOKIE_KEY = "ogna_token";

export function middleware(req: NextRequest) {
  // Read the token from the mirrored cookie
  const token = req.cookies.get(COOKIE_KEY)?.value;

  // If the user tries to access /protected/* without a token, redirect to login
  if (!token && req.nextUrl.pathname.startsWith("/protected")) {
    return NextResponse.redirect(new URL("/account/login", req.url));
  }

  // Otherwise, continue
  return NextResponse.next();
}

// Apply middleware only to protected routes
export const config = {
  matcher: ["/protected/:path*"],
};
