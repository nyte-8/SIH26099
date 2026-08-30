# main.py

from matching import process_and_save_data
from database import setup_database, get_common_materials_summary
import time


def main():
    """Main function to orchestrate the entire Material Master Framework
    as a one-shot batch run over dataset.csv."""
    print("=====================================================")
    print(" National Unified Material Master Framework Started")
    print("=====================================================")

    setup_database()
    print("\nDatabase initialized.")

    start_time = time.time()
    try:
        results = process_and_save_data()
        end_time = time.time()

        print("\n=====================================================")
        print("SUCCESS: Material Processing Complete")
        print(f"Total execution time: {end_time - start_time:.2f} seconds")
        if results:
            print(f"Processed {len(results)} source records.")
            summary = get_common_materials_summary()
            print(f"They consolidated into {len(summary)} unique common material code(s):")
            for item in summary:
                print(f"  {item['common_code']}: {item['standard_description']} "
                      f"[{item['category']}] <- {item['record_count']} source record(s)")
        else:
            print("No records were successfully processed or saved.")
        print("=====================================================")

    except Exception as e:
        print(f"\nFATAL ERROR during execution: {e}")
        print("Process halted.")


if __name__ == "__main__":
    main()
