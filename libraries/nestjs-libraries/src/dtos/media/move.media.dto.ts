import { IsArray, IsString, IsOptional, ArrayMinSize } from 'class-validator';

/** DTO for moving one or more media items into a folder (or back to root). */
export class MoveMediaDto {
  @IsArray()
  @ArrayMinSize(1)
  @IsString({ each: true })
  ids: string[];

  /** Target folder name. `null` moves items back to root (no folder). */
  @IsOptional()
  @IsString()
  folder: string | null;
}
