"use client";

import { FileText } from "lucide-react";

interface Props {
  citation: string;
}

export default function CitationLink({ citation }: Props) {
  return (
    <div className="mt-2 inline-flex items-center gap-2 rounded-md bg-indigo-50 px-3 py-1.5 text-sm text-indigo-700">
      <FileText className="h-4 w-4" />
      <span className="font-medium">{citation}</span>
    </div>
  );
}
