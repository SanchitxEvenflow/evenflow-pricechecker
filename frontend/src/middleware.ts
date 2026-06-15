import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const AUTH_ENABLED = process.env.NEXT_PUBLIC_AUTH_ENABLED === "true";

export function middleware(request: NextRequest) {
  if (!AUTH_ENABLED) return NextResponse.next();

  const isLogin = request.nextUrl.pathname === "/login";
  const hasAuth = request.cookies.get("pc_auth")?.value === "1";

  if (!hasAuth && !isLogin) {
    return NextResponse.redirect(new URL("/login", request.url));
  }
  if (hasAuth && isLogin) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|ico|webp)).*)"],
};
