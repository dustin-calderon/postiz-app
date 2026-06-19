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
