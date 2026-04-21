const fallbackCopyTextToClipboard = (value: string) => {
  if (typeof document === 'undefined' || !document.body) {
    throw new Error('Clipboard copy is unavailable in this context.');
  }

  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.top = '0';
  textarea.style.left = '-9999px';
  textarea.style.opacity = '0';
  textarea.style.pointerEvents = 'none';

  const selection = document.getSelection();
  const previousRanges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index))
    : [];
  const activeElement = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();
  textarea.setSelectionRange(0, textarea.value.length);

  let copied = false;
  try {
    copied = document.execCommand('copy');
  } finally {
    document.body.removeChild(textarea);
    if (selection) {
      selection.removeAllRanges();
      previousRanges.forEach((range) => selection.addRange(range));
    }
    activeElement?.focus();
  }

  if (!copied) {
    throw new Error('Clipboard copy is unavailable in this browser.');
  }
};

export const copyTextToClipboard = async (value: string) => {
  if (typeof window === 'undefined') {
    throw new Error('Clipboard copy is unavailable in this context.');
  }

  const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
  const permissions = typeof navigator !== 'undefined' ? navigator.permissions : undefined;
  const canUseAsyncClipboard = Boolean(clipboard?.writeText) && window.isSecureContext;

  if (canUseAsyncClipboard && clipboard) {
    const permissionStatus = permissions
      ? await permissions.query({ name: 'clipboard-write' as PermissionName }).catch(() => null)
      : null;

    if (permissionStatus?.state !== 'denied') {
      try {
        await clipboard.writeText(value);
        return;
      } catch {
        // Fall through to the legacy copy path below.
      }
    }
  }

  fallbackCopyTextToClipboard(value);
};
