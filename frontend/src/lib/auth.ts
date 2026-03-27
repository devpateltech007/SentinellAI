import { api } from "./api";
import type { User, TokenResponse } from "./types";

const TOKEN_KEY = "sentinellai_token";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export async function loginUser(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return api.post<TokenResponse>("/auth/login", { email, password });
}

export async function registerUser(
  email: string,
  password: string,
  role: string,
): Promise<User> {
  return api.post<User>("/auth/register", { email, password, role });
}

export async function fetchCurrentUser(): Promise<User> {
  return api.get<User>("/auth/me");
}
