import { IsString, MinLength } from 'class-validator';

/** DTO for renaming an existing media folder. */
export class RenameFolderDto {
  @IsString()
  @MinLength(1)
  oldName: string;

  @IsString()
  @MinLength(1)
  newName: string;
}

/**
 * Where `folder` ends up after renaming `oldName` to `newName`, or `null` when
 * the rename does not reach it. Same rule as `MediaRepository.renameFolder`:
 * both names are trimmed, and only the folder itself and the paths below it
 * (`<oldName>/…`) are renamed, so renaming `Citem` leaves `Citem2` alone.
 */
export const renamedFolderPath = (
  folder: string,
  oldName: string,
  newName: string
): string | null => {
  const oldTrimmed = oldName.trim();
  const newTrimmed = newName.trim();
  if (oldTrimmed === newTrimmed) {
    return null;
  }
  if (folder !== oldTrimmed && !folder.startsWith(`${oldTrimmed}/`)) {
    return null;
  }
  return newTrimmed + folder.slice(oldTrimmed.length);
};
