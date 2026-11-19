// 품목 이름과 함께 쓰는 장식용 도형이다.
export function CropIcon({ crop }: { crop: string }) {
  return <span aria-hidden="true" className={`crop-icon crop-icon--${crop}`} />;
}
