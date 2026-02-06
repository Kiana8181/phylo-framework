export default function FileInput({
  accept,
  multiple,
  onFiles,
  disabled = false,
}: {
  accept?: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}) {
  return (
    <input
      type="file"
      multiple={multiple}
      onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      className="block"
      accept={accept}
      disabled={disabled}
    />
  );
}
