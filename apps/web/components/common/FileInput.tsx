export default function FileInput({
  accept,
  multiple,
  onFiles,
}: {
  accept?: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
}) {
  return (
    <input
      type="file"
      multiple={multiple}
      onChange={(e) => onFiles(Array.from(e.target.files ?? []))}
      className="block"
      accept={accept}
    />
  );
}
