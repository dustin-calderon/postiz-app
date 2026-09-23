const config = {
  displayName: 'nestjs-libraries',
  testEnvironment: 'node',
  testMatch: ['<rootDir>/src/**/*.spec.ts'],
  transform: {
    '^.+\\.ts$': ['ts-jest', { tsconfig: '<rootDir>/tsconfig.spec.json' }],
  },
  // The tsconfig.base.json aliases this library imports from.
  moduleNameMapper: {
    '^@gitroom/nestjs-libraries/(.*)$': '<rootDir>/src/$1',
    '^@gitroom/helpers/(.*)$': '<rootDir>/../helpers/src/$1',
    '^@gitroom/backend/(.*)$': '<rootDir>/../../apps/backend/src/$1',
  },
};

export default config;
