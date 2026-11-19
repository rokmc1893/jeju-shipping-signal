import carrot from "../assets/crops/carrot.png";
import radish from "../assets/crops/radish.png";
import cabbage from "../assets/crops/cabbage.png";
import garlic from "../assets/crops/garlic.png";
import onion from "../assets/crops/onion.png";

const illustrations = new Map([
  ["carrot", carrot],
  ["radish", radish],
  ["cabbage", cabbage],
  ["garlic", garlic],
  ["onion", onion],
]);

export function CropIcon({ crop }: { crop: string }) {
  const illustration = illustrations.get(crop);
  return (
    <span aria-hidden="true" className={`crop-icon crop-icon--${crop}`}>
      {illustration && <img src={illustration} alt="" width={144} height={144} />}
    </span>
  );
}
