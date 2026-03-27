"use client";

import { useEffect, useState } from "react";
import { fetchCurrentUser } from "@/lib/auth";
import type { User } from "@/lib/types";

export default function Header() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    fetchCurrentUser().then(setUser).catch(() => {});
  }, []);

  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-200 bg-white px-8">
      <h1 className="text-lg font-semibold text-slate-800">
        Compliance Auditing Platform
      </h1>
      {user && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-600">{user.email}</span>
          <span className="rounded-full bg-indigo-100 px-3 py-1 text-xs font-medium text-indigo-700">
            {user.role.replace("_", " ")}
          </span>
        </div>
      )}
    </header>
  );
}
