import {
  ValidationArguments,
  ValidatorConstraintInterface,
  ValidatorConstraint,
} from 'class-validator';
import { VIDEO_EXTENSIONS } from '@gitroom/helpers/utils/has.extension';

// Mirrors the image MIME types accepted by the upload pipeline
// (local.storage.ts / custom.upload.validation.ts): jpeg, png, gif, webp,
// avif, bmp, tiff. `.tif` and `.tiff` both map to image/tiff.
const IMAGE_EXTENSIONS = [
  'png',
  'jpg',
  'jpeg',
  'gif',
  'webp',
  'avif',
  'bmp',
  'tif',
  'tiff',
] as const;
const VALID_UPLOAD_EXTENSIONS = [
  ...IMAGE_EXTENSIONS,
  ...VIDEO_EXTENSIONS,
] as const;

@ValidatorConstraint({ name: 'checkValidExtension', async: false })
export class ValidUrlExtension implements ValidatorConstraintInterface {
  validate(text: string, args: ValidationArguments) {
    // Strip any query string (R2/S3 signed URLs) before checking the extension.
    const path = text?.split?.('?')?.[0]?.toLowerCase() ?? '';
    return VALID_UPLOAD_EXTENSIONS.some((ext) => path.endsWith(`.${ext}`));
  }

  defaultMessage(args: ValidationArguments) {
    // here you can provide default error message if validation failed
    return (
      'File must have a valid extension: ' +
      VALID_UPLOAD_EXTENSIONS.map((e) => `.${e}`).join(', ')
    );
  }
}

@ValidatorConstraint({ name: 'checkValidPath', async: false })
export class ValidUrlPath implements ValidatorConstraintInterface {
  validate(text: string, args: ValidationArguments) {
    if (!process.env.RESTRICT_UPLOAD_DOMAINS) {
      return true;
    }

    return (
      (text || 'invalid url').indexOf(process.env.RESTRICT_UPLOAD_DOMAINS) > -1
    );
  }

  defaultMessage(args: ValidationArguments) {
    // here you can provide default error message if validation failed
    return (
      'URL must contain the domain: ' + process.env.RESTRICT_UPLOAD_DOMAINS + ' Make sure you first use the upload API route.'
    );
  }
}
