import { IsArray, IsString, ValidateIf, ArrayMinSize } from 'class-validator';

/** DTO for moving one or more media items into a folder (or back to root). */
export class MoveMediaDto {
  @IsArray()
  @ArrayMinSize(1)
  @IsString({ each: true })
  ids: string[];

  /**
   * Target folder name. `null` moves items back to root (no folder).
   * `@ValidateIf` skips @IsString when the value is explicitly null,
   * because @IsOptional only skips undefined — not null.
   */
  @ValidateIf((o: MoveMediaDto) => o.folder !== null)
  @IsString()
  folder: string | null;
}
