'use client';

import type { MouseEvent, ReactNode } from 'react';

const DOCX_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';

type SavePicker = (options: {
  id?: string;
  startIn?: 'downloads' | 'documents' | 'desktop';
  suggestedName?: string;
  types?: { description: string; accept: Record<string, string[]> }[];
}) => Promise<FileSystemFileHandle>;

/**
 * A download link that asks where to save the file.
 *
 * In Chrome and Edge it opens the "Save as" dialog: the first time in
 * Downloads, after that in the folder you last saved to (the browser remembers
 * it). Other browsers save the usual way, to their download folder.
 */
export function DownloadLink({
  href,
  filename,
  className,
  title,
  children,
}: {
  href: string;
  filename: string;
  className?: string;
  title?: string;
  children: ReactNode;
}) {
  const onClick = async (event: MouseEvent<HTMLAnchorElement>) => {
    const picker = (window as unknown as { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
    if (!picker) return; // normal download
    event.preventDefault();

    let handle: FileSystemFileHandle;
    try {
      // Open the dialog first: it must follow the click directly.
      handle = await picker({
        id: 'lokishift-downloads',
        startIn: 'downloads',
        suggestedName: filename,
        types: [{ description: 'Word document', accept: { [DOCX_TYPE]: ['.docx'] } }],
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return; // cancelled
      fallbackDownload(href, filename);
      return;
    }

    try {
      const response = await fetch(href);
      if (!response.ok) throw new Error(`Download failed (${response.status})`);
      const writable = await handle.createWritable();
      await response.body!.pipeTo(writable);
    } catch {
      fallbackDownload(href, filename);
    }
  };

  return (
    <a href={href} download={filename} onClick={onClick} className={className} title={title}>
      {children}
    </a>
  );
}

function fallbackDownload(href: string, filename: string) {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
